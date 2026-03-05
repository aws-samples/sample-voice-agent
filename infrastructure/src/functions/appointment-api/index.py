"""
Appointment Scheduling API Lambda Handler

Provides REST API endpoints for managing technician appointments.
Designed for integration with the voice agent appointment scheduling capability.

DynamoDB Schema:
  Appointments table:
    PK: appointment_id (String)
    GSIs:
      - customer-index: customer_id (PK), appointment_date (SK)
      - date-index: appointment_date (PK), start_time (SK)
      - status-index: status (PK), appointment_date (SK)
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb")

# Get table name from environment
appointments_table_name = os.environ.get("APPOINTMENTS_TABLE", "")

# Initialize table reference
appointments_table = (
    dynamodb.Table(appointments_table_name) if appointments_table_name else None
)

# Service types and their durations (minutes)
SERVICE_TYPES = {
    "on_site_repair": {"label": "On-site Repair", "duration_minutes": 60},
    "network_setup": {"label": "Network Setup", "duration_minutes": 90},
    "hardware_upgrade": {"label": "Hardware Upgrade", "duration_minutes": 120},
    "general_consultation": {"label": "General Consultation", "duration_minutes": 30},
    "preventive_maintenance": {
        "label": "Preventive Maintenance",
        "duration_minutes": 45,
    },
}

# Business hours
BUSINESS_START_HOUR = 9  # 9 AM
BUSINESS_END_HOUR = 17  # 5 PM
SLOT_INTERVAL_MINUTES = 30


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types from DynamoDB."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def create_response(status_code: int, body: Any) -> Dict[str, Any]:
    """Create API Gateway response with proper headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def generate_appointment_id() -> str:
    """Generate a unique appointment ID."""
    year = datetime.now().year
    random_suffix = uuid.uuid4().hex[:6].upper()
    return f"APPT-{year}-{random_suffix}"


def validate_date_format(date_str: str) -> bool:
    """Validate date string is YYYY-MM-DD format."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_time_format(time_str: str) -> bool:
    """Validate time string is HH:MM format."""
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False


def is_business_hours(time_str: str, duration_minutes: int = 30) -> bool:
    """Check if a time slot falls within business hours."""
    t = datetime.strptime(time_str, "%H:%M")
    start_minutes = t.hour * 60 + t.minute
    end_minutes = start_minutes + duration_minutes
    return (
        start_minutes >= BUSINESS_START_HOUR * 60
        and end_minutes <= BUSINESS_END_HOUR * 60
    )


def is_future_date(date_str: str) -> bool:
    """Check if a date is today or in the future."""
    appt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = datetime.now().date()
    return appt_date >= today


def generate_time_slots(
    date_str: str, service_type: str, booked_slots: List[Dict]
) -> List[Dict[str, str]]:
    """Generate available time slots for a given date and service type.

    Args:
        date_str: Date in YYYY-MM-DD format
        service_type: The service type key
        booked_slots: List of existing appointments on that date

    Returns:
        List of available slot dicts with start_time and end_time.
    """
    service_info = SERVICE_TYPES.get(service_type)
    if not service_info:
        return []

    duration = service_info["duration_minutes"]

    # Build set of booked time ranges (start_minutes, end_minutes)
    booked_ranges = []
    for appt in booked_slots:
        if appt.get("status") in ("cancelled",):
            continue
        t = datetime.strptime(appt["start_time"], "%H:%M")
        s = t.hour * 60 + t.minute
        appt_service = SERVICE_TYPES.get(appt.get("service_type", ""), {})
        d = appt_service.get("duration_minutes", 60)
        booked_ranges.append((s, s + d))

    # Generate candidate slots
    available = []
    current = BUSINESS_START_HOUR * 60

    while current + duration <= BUSINESS_END_HOUR * 60:
        end = current + duration
        # Check for overlap with any booked range
        conflict = False
        for bs, be in booked_ranges:
            if current < be and end > bs:  # overlap check
                conflict = True
                break

        if not conflict:
            start_h, start_m = divmod(current, 60)
            end_h, end_m = divmod(end, 60)
            available.append(
                {
                    "start_time": f"{start_h:02d}:{start_m:02d}",
                    "end_time": f"{end_h:02d}:{end_m:02d}",
                }
            )

        current += SLOT_INTERVAL_MINUTES

    return available


# ==========================================
# Appointment Handlers
# ==========================================


def handle_check_availability(event: Dict[str, Any]) -> Dict[str, Any]:
    """Check available appointment slots for a date and service type.

    Query params: date (YYYY-MM-DD), service_type
    """
    params = event.get("queryStringParameters") or {}
    date_str = params.get("date")
    service_type = params.get("service_type")

    if not date_str:
        return create_response(400, {"error": "Missing required parameter: date"})

    if not validate_date_format(date_str):
        return create_response(400, {"error": "Invalid date format. Use YYYY-MM-DD."})

    if not is_future_date(date_str):
        return create_response(400, {"error": "Date must be today or in the future."})

    if not service_type:
        # Default to general_consultation if not specified
        service_type = "general_consultation"

    if service_type not in SERVICE_TYPES:
        return create_response(
            400,
            {
                "error": f"Invalid service_type. Must be one of: {', '.join(SERVICE_TYPES.keys())}",
            },
        )

    try:
        # Query existing appointments for the date
        response = appointments_table.query(
            IndexName="date-index",
            KeyConditionExpression=Key("appointment_date").eq(date_str),
        )
        booked = response.get("Items", [])

        available_slots = generate_time_slots(date_str, service_type, booked)

        service_info = SERVICE_TYPES[service_type]

        return create_response(
            200,
            {
                "date": date_str,
                "service_type": service_type,
                "service_label": service_info["label"],
                "duration_minutes": service_info["duration_minutes"],
                "available_slots": available_slots,
                "total_available": len(available_slots),
            },
        )

    except Exception as e:
        print(f"Error checking availability: {str(e)}")
        return create_response(
            500, {"error": "Failed to check availability", "message": str(e)}
        )


def handle_book_appointment(event: Dict[str, Any]) -> Dict[str, Any]:
    """Book a new appointment.

    Body: customer_id, date (YYYY-MM-DD), start_time (HH:MM), service_type, notes (optional)
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    # Validate required fields
    required = ["customer_id", "date", "start_time", "service_type"]
    for field in required:
        if field not in body or not body[field]:
            return create_response(400, {"error": f"Missing required field: {field}"})

    date_str = body["date"]
    start_time = body["start_time"]
    service_type = body["service_type"]
    customer_id = body["customer_id"]

    if not validate_date_format(date_str):
        return create_response(400, {"error": "Invalid date format. Use YYYY-MM-DD."})

    if not validate_time_format(start_time):
        return create_response(400, {"error": "Invalid time format. Use HH:MM."})

    if not is_future_date(date_str):
        return create_response(400, {"error": "Date must be today or in the future."})

    if service_type not in SERVICE_TYPES:
        return create_response(
            400,
            {
                "error": f"Invalid service_type. Must be one of: {', '.join(SERVICE_TYPES.keys())}"
            },
        )

    service_info = SERVICE_TYPES[service_type]
    duration = service_info["duration_minutes"]

    if not is_business_hours(start_time, duration):
        return create_response(
            400,
            {
                "error": f"Appointment must be within business hours ({BUSINESS_START_HOUR}:00-{BUSINESS_END_HOUR}:00) and fit within the day."
            },
        )

    try:
        # Check for conflicts
        response = appointments_table.query(
            IndexName="date-index",
            KeyConditionExpression=Key("appointment_date").eq(date_str),
        )
        existing = response.get("Items", [])

        t = datetime.strptime(start_time, "%H:%M")
        new_start = t.hour * 60 + t.minute
        new_end = new_start + duration

        for appt in existing:
            if appt.get("status") == "cancelled":
                continue
            at = datetime.strptime(appt["start_time"], "%H:%M")
            appt_start = at.hour * 60 + at.minute
            appt_service = SERVICE_TYPES.get(appt.get("service_type", ""), {})
            appt_duration = appt_service.get("duration_minutes", 60)
            appt_end = appt_start + appt_duration

            if new_start < appt_end and new_end > appt_start:
                return create_response(
                    409,
                    {
                        "error": "Time slot conflict",
                        "message": f"Conflicts with existing appointment {appt['appointment_id']} at {appt['start_time']}.",
                        "conflicting_appointment": appt["appointment_id"],
                    },
                )

        # Calculate end time
        end_h, end_m = divmod(new_end, 60)
        end_time = f"{end_h:02d}:{end_m:02d}"

        now = datetime.now().isoformat()
        appointment = {
            "appointment_id": generate_appointment_id(),
            "customer_id": customer_id,
            "appointment_date": date_str,
            "start_time": start_time,
            "end_time": end_time,
            "service_type": service_type,
            "service_label": service_info["label"],
            "duration_minutes": duration,
            "status": "confirmed",
            "notes": body.get("notes", ""),
            "created_at": now,
            "updated_at": now,
        }

        appointments_table.put_item(Item=appointment)

        return create_response(201, appointment)

    except Exception as e:
        if "409" not in str(type(e)):
            print(f"Error booking appointment: {str(e)}")
        return create_response(
            500, {"error": "Failed to book appointment", "message": str(e)}
        )


def handle_get_appointment(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get a specific appointment by ID."""
    path_params = event.get("pathParameters") or {}
    appointment_id = path_params.get("appointmentId")

    if not appointment_id:
        return create_response(400, {"error": "Missing appointment ID"})

    try:
        response = appointments_table.query(
            KeyConditionExpression=Key("appointment_id").eq(appointment_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Appointment not found"})

        return create_response(200, items[0])

    except Exception as e:
        print(f"Error getting appointment: {str(e)}")
        return create_response(
            500, {"error": "Failed to get appointment", "message": str(e)}
        )


def handle_cancel_appointment(event: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel an existing appointment.

    Body: reason (optional)
    """
    path_params = event.get("pathParameters") or {}
    appointment_id = path_params.get("appointmentId")

    if not appointment_id:
        return create_response(400, {"error": "Missing appointment ID"})

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        body = {}

    try:
        # Get existing appointment
        response = appointments_table.query(
            KeyConditionExpression=Key("appointment_id").eq(appointment_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Appointment not found"})

        existing = items[0]

        if existing.get("status") == "cancelled":
            return create_response(400, {"error": "Appointment is already cancelled"})

        now = datetime.now().isoformat()

        appointments_table.update_item(
            Key={"appointment_id": appointment_id},
            UpdateExpression="SET #s = :status, cancellation_reason = :reason, cancelled_at = :cancelled_at, updated_at = :updated_at",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "cancelled",
                ":reason": body.get("reason", "Cancelled by caller"),
                ":cancelled_at": now,
                ":updated_at": now,
            },
            ReturnValues="ALL_NEW",
        )

        # Get updated appointment
        response = appointments_table.query(
            KeyConditionExpression=Key("appointment_id").eq(appointment_id)
        )

        return create_response(200, response["Items"][0])

    except Exception as e:
        print(f"Error cancelling appointment: {str(e)}")
        return create_response(
            500, {"error": "Failed to cancel appointment", "message": str(e)}
        )


def handle_reschedule_appointment(event: Dict[str, Any]) -> Dict[str, Any]:
    """Reschedule an existing appointment.

    Body: new_date (YYYY-MM-DD), new_time (HH:MM)
    """
    path_params = event.get("pathParameters") or {}
    appointment_id = path_params.get("appointmentId")

    if not appointment_id:
        return create_response(400, {"error": "Missing appointment ID"})

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    new_date = body.get("new_date")
    new_time = body.get("new_time")

    if not new_date or not new_time:
        return create_response(
            400, {"error": "Missing required fields: new_date, new_time"}
        )

    if not validate_date_format(new_date):
        return create_response(400, {"error": "Invalid date format. Use YYYY-MM-DD."})

    if not validate_time_format(new_time):
        return create_response(400, {"error": "Invalid time format. Use HH:MM."})

    if not is_future_date(new_date):
        return create_response(
            400, {"error": "New date must be today or in the future."}
        )

    try:
        # Get existing appointment
        response = appointments_table.query(
            KeyConditionExpression=Key("appointment_id").eq(appointment_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Appointment not found"})

        existing = items[0]

        if existing.get("status") == "cancelled":
            return create_response(
                400, {"error": "Cannot reschedule a cancelled appointment"}
            )

        service_type = existing["service_type"]
        service_info = SERVICE_TYPES.get(service_type, {})
        duration = service_info.get("duration_minutes", 60)

        if not is_business_hours(new_time, duration):
            return create_response(
                400,
                {
                    "error": f"Appointment must be within business hours ({BUSINESS_START_HOUR}:00-{BUSINESS_END_HOUR}:00)."
                },
            )

        # Check for conflicts on the new date (excluding current appointment)
        date_response = appointments_table.query(
            IndexName="date-index",
            KeyConditionExpression=Key("appointment_date").eq(new_date),
        )
        existing_on_date = [
            a
            for a in date_response.get("Items", [])
            if a["appointment_id"] != appointment_id and a.get("status") != "cancelled"
        ]

        t = datetime.strptime(new_time, "%H:%M")
        new_start = t.hour * 60 + t.minute
        new_end = new_start + duration

        for appt in existing_on_date:
            at = datetime.strptime(appt["start_time"], "%H:%M")
            appt_start = at.hour * 60 + at.minute
            appt_service = SERVICE_TYPES.get(appt.get("service_type", ""), {})
            appt_duration = appt_service.get("duration_minutes", 60)
            appt_end = appt_start + appt_duration

            if new_start < appt_end and new_end > appt_start:
                return create_response(
                    409,
                    {
                        "error": "Time slot conflict on the new date",
                        "conflicting_appointment": appt["appointment_id"],
                    },
                )

        # Calculate new end time
        end_h, end_m = divmod(new_end, 60)
        new_end_time = f"{end_h:02d}:{end_m:02d}"

        now = datetime.now().isoformat()
        old_date = existing["appointment_date"]
        old_time = existing["start_time"]

        appointments_table.update_item(
            Key={"appointment_id": appointment_id},
            UpdateExpression=(
                "SET appointment_date = :new_date, start_time = :new_time, "
                "end_time = :new_end_time, "
                "previous_date = :old_date, previous_time = :old_time, "
                "updated_at = :updated_at"
            ),
            ExpressionAttributeValues={
                ":new_date": new_date,
                ":new_time": new_time,
                ":new_end_time": new_end_time,
                ":old_date": old_date,
                ":old_time": old_time,
                ":updated_at": now,
            },
            ReturnValues="ALL_NEW",
        )

        # Get updated appointment
        response = appointments_table.query(
            KeyConditionExpression=Key("appointment_id").eq(appointment_id)
        )

        return create_response(200, response["Items"][0])

    except Exception as e:
        print(f"Error rescheduling appointment: {str(e)}")
        return create_response(
            500, {"error": "Failed to reschedule appointment", "message": str(e)}
        )


def handle_list_appointments(event: Dict[str, Any]) -> Dict[str, Any]:
    """List appointments for a customer or by date.

    Query params: customer_id, date, status, limit
    """
    params = event.get("queryStringParameters") or {}

    try:
        # By customer
        if "customer_id" in params:
            customer_id = params["customer_id"]
            query_params = {
                "IndexName": "customer-index",
                "KeyConditionExpression": Key("customer_id").eq(customer_id),
                "ScanIndexForward": True,  # Chronological order
            }
            if "status" in params:
                query_params["FilterExpression"] = Attr("status").eq(params["status"])

            response = appointments_table.query(**query_params)
            return create_response(200, response.get("Items", []))

        # By date
        if "date" in params:
            date_str = params["date"]
            if not validate_date_format(date_str):
                return create_response(
                    400, {"error": "Invalid date format. Use YYYY-MM-DD."}
                )

            query_params = {
                "IndexName": "date-index",
                "KeyConditionExpression": Key("appointment_date").eq(date_str),
                "ScanIndexForward": True,
            }
            if "status" in params:
                query_params["FilterExpression"] = Attr("status").eq(params["status"])

            response = appointments_table.query(**query_params)
            return create_response(200, response.get("Items", []))

        # By status
        if "status" in params:
            response = appointments_table.query(
                IndexName="status-index",
                KeyConditionExpression=Key("status").eq(params["status"]),
                ScanIndexForward=True,
            )
            return create_response(200, response.get("Items", []))

        # All appointments (with limit)
        limit = int(params.get("limit", 50))
        response = appointments_table.scan(Limit=limit)
        return create_response(200, response.get("Items", []))

    except Exception as e:
        print(f"Error listing appointments: {str(e)}")
        return create_response(
            500, {"error": "Failed to list appointments", "message": str(e)}
        )


# ==========================================
# Admin Handlers (Demo Data)
# ==========================================


def handle_seed_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """Load demo appointment data for testing."""
    try:
        now = datetime.now()
        today = now.date()

        # Generate appointments for the next 14 days
        demo_appointments = []

        # Some pre-booked appointments to make the schedule realistic
        base_appointments = [
            {
                "customer_id": "cust-001",
                "service_type": "on_site_repair",
                "day_offset": 1,
                "start_time": "10:00",
                "notes": "Laptop screen replacement",
            },
            {
                "customer_id": "cust-002",
                "service_type": "network_setup",
                "day_offset": 1,
                "start_time": "14:00",
                "notes": "Home office network configuration",
            },
            {
                "customer_id": "cust-003",
                "service_type": "hardware_upgrade",
                "day_offset": 2,
                "start_time": "09:00",
                "notes": "Server RAM and SSD upgrade",
            },
            {
                "customer_id": "cust-001",
                "service_type": "preventive_maintenance",
                "day_offset": 3,
                "start_time": "11:00",
                "notes": "Quarterly system check",
            },
            {
                "customer_id": "cust-002",
                "service_type": "general_consultation",
                "day_offset": 5,
                "start_time": "15:00",
                "notes": "Discuss cloud migration options",
            },
            {
                "customer_id": "cust-003",
                "service_type": "on_site_repair",
                "day_offset": 7,
                "start_time": "10:30",
                "notes": "Printer network connectivity issue",
            },
        ]

        for base in base_appointments:
            appt_date = today + timedelta(days=base["day_offset"])
            # Skip weekends
            if appt_date.weekday() >= 5:
                appt_date += timedelta(days=7 - appt_date.weekday())

            date_str = appt_date.strftime("%Y-%m-%d")
            service_info = SERVICE_TYPES[base["service_type"]]
            duration = service_info["duration_minutes"]

            t = datetime.strptime(base["start_time"], "%H:%M")
            end_minutes = t.hour * 60 + t.minute + duration
            end_h, end_m = divmod(end_minutes, 60)

            appointment = {
                "appointment_id": generate_appointment_id(),
                "customer_id": base["customer_id"],
                "appointment_date": date_str,
                "start_time": base["start_time"],
                "end_time": f"{end_h:02d}:{end_m:02d}",
                "service_type": base["service_type"],
                "service_label": service_info["label"],
                "duration_minutes": duration,
                "status": "confirmed",
                "notes": base["notes"],
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }

            demo_appointments.append(appointment)

        # Insert all appointments
        for appt in demo_appointments:
            appointments_table.put_item(Item=appt)

        return create_response(
            200,
            {
                "message": "Demo appointment data seeded successfully",
                "appointments_seeded": len(demo_appointments),
                "date_range": {
                    "from": (today + timedelta(days=1)).strftime("%Y-%m-%d"),
                    "to": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
                },
                "service_types": list(SERVICE_TYPES.keys()),
            },
        )

    except Exception as e:
        print(f"Error seeding demo data: {str(e)}")
        return create_response(
            500, {"error": "Failed to seed demo data", "message": str(e)}
        )


def handle_reset_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """Clear all appointment data (use with caution!)."""
    try:
        response = appointments_table.scan()
        items = response.get("Items", [])

        for item in items:
            appointments_table.delete_item(
                Key={"appointment_id": item["appointment_id"]}
            )

        return create_response(
            200,
            {
                "message": "All appointment data cleared successfully",
                "appointments_deleted": len(items),
            },
        )

    except Exception as e:
        print(f"Error resetting data: {str(e)}")
        return create_response(
            500, {"error": "Failed to reset data", "message": str(e)}
        )


# ==========================================
# Main Handler
# ==========================================


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main Lambda handler - routes requests to appropriate handlers."""

    http_method = event.get("httpMethod", "")
    path = event.get("path", "")

    print(f"Received request: {http_method} {path}")

    # Handle CORS preflight
    if http_method == "OPTIONS":
        return create_response(200, {"message": "OK"})

    # Route to appropriate handler
    try:
        # Availability check
        if path == "/availability":
            if http_method == "GET":
                return handle_check_availability(event)

        # Appointments CRUD
        elif path == "/appointments":
            if http_method == "GET":
                return handle_list_appointments(event)
            elif http_method == "POST":
                return handle_book_appointment(event)

        elif path.startswith("/appointments/"):
            parts = path.split("/")
            if len(parts) >= 3:
                appointment_id = parts[2]

                # /appointments/{id}/cancel
                if len(parts) == 4 and parts[3] == "cancel":
                    if http_method == "POST":
                        return handle_cancel_appointment(event)

                # /appointments/{id}/reschedule
                elif len(parts) == 4 and parts[3] == "reschedule":
                    if http_method == "POST":
                        return handle_reschedule_appointment(event)

                # /appointments/{id}
                elif len(parts) == 3:
                    if http_method == "GET":
                        return handle_get_appointment(event)

        # Service types reference
        elif path == "/service-types":
            if http_method == "GET":
                return create_response(200, SERVICE_TYPES)

        # Admin endpoints
        elif path == "/admin/seed":
            if http_method == "POST":
                return handle_seed_data(event)

        elif path == "/admin/reset":
            if http_method == "DELETE":
                return handle_reset_data(event)

        # Health check
        elif path == "/health":
            return create_response(
                200,
                {
                    "status": "healthy",
                    "tables": {
                        "appointments": appointments_table_name,
                    },
                },
            )

        # If no route matched
        return create_response(
            404, {"error": "Not found", "path": path, "method": http_method}
        )

    except Exception as e:
        print(f"Unhandled error: {str(e)}")
        import traceback

        traceback.print_exc()
        return create_response(
            500, {"error": "Internal server error", "message": str(e)}
        )
