"""
CRM API Lambda Handler

Provides REST API endpoints for customer data, cases, and interaction tracking.
Designed for integration with voice agent applications.
"""

import json
import os
import uuid
import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional, List
import boto3
from boto3.dynamodb.conditions import Key, Attr

# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb")

# Get table names from environment
customers_table_name = os.environ.get("CUSTOMERS_TABLE", "")
cases_table_name = os.environ.get("CASES_TABLE", "")
interactions_table_name = os.environ.get("INTERACTIONS_TABLE", "")

# Initialize table references
customers_table = dynamodb.Table(customers_table_name) if customers_table_name else None
cases_table = dynamodb.Table(cases_table_name) if cases_table_name else None
interactions_table = (
    dynamodb.Table(interactions_table_name) if interactions_table_name else None
)


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


def generate_customer_id() -> str:
    """Generate a unique customer ID."""
    return f"cust-{uuid.uuid4().hex[:12]}"


def generate_case_id() -> str:
    """Generate a case ID in TICKET-YYYY-XXXXX format."""
    year = datetime.now().year
    random_suffix = uuid.uuid4().hex[:5].upper()
    return f"TICKET-{year}-{random_suffix}"


def generate_interaction_id() -> str:
    """Generate a unique interaction ID."""
    return f"int-{uuid.uuid4().hex[:12]}"


def validate_customer_data(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate customer data before creation/update."""
    required_fields = ["phone", "first_name", "last_name"]

    for field in required_fields:
        if field not in data or not data[field]:
            return False, f"Missing required field: {field}"

    # Validate phone format (basic validation)
    phone = data.get("phone", "")
    if not re.match(r"^[\d\-\(\)\s\+]+$", phone):
        return False, "Invalid phone number format"

    return True, None


def validate_case_data(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate case data before creation."""
    if "customer_id" not in data or not data["customer_id"]:
        return False, "Missing required field: customer_id"

    if "subject" not in data or not data["subject"]:
        return False, "Missing required field: subject"

    return True, None


# ==========================================
# Customer Handlers
# ==========================================


def handle_get_customers(event: Dict[str, Any]) -> Dict[str, Any]:
    """Search customers by phone or email."""
    params = event.get("queryStringParameters") or {}

    try:
        # Search by phone (using GSI)
        if "phone" in params:
            phone = params["phone"]
            response = customers_table.query(
                IndexName="phone-index", KeyConditionExpression=Key("phone").eq(phone)
            )
            return create_response(200, response.get("Items", []))

        # Search by email (using GSI)
        if "email" in params:
            email = params["email"]
            response = customers_table.query(
                IndexName="email-index", KeyConditionExpression=Key("email").eq(email)
            )
            return create_response(200, response.get("Items", []))

        # List all customers (with limit)
        limit = int(params.get("limit", 50))
        response = customers_table.scan(Limit=limit)
        return create_response(200, response.get("Items", []))

    except Exception as e:
        print(f"Error searching customers: {str(e)}")
        return create_response(
            500, {"error": "Failed to search customers", "message": str(e)}
        )


def handle_get_customer(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get a specific customer by ID."""
    path_params = event.get("pathParameters") or {}
    customer_id = path_params.get("customerId")

    if not customer_id:
        return create_response(400, {"error": "Missing customer ID"})

    try:
        # We need to query by customer_id since it's the partition key
        # But we don't have the sort key (phone), so we scan with filter
        response = customers_table.scan(
            FilterExpression=Attr("customer_id").eq(customer_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Customer not found"})

        return create_response(200, items[0])

    except Exception as e:
        print(f"Error getting customer: {str(e)}")
        return create_response(
            500, {"error": "Failed to get customer", "message": str(e)}
        )


def handle_create_customer(event: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new customer."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    # Validate input
    is_valid, error_message = validate_customer_data(body)
    if not is_valid:
        return create_response(400, {"error": error_message})

    try:
        now = datetime.now().isoformat()

        customer = {
            "customer_id": generate_customer_id(),
            "phone": body["phone"],
            "email": body.get("email"),
            "first_name": body["first_name"],
            "last_name": body["last_name"],
            "account_type": body.get("account_type", "basic"),
            "account_status": body.get("account_status", "active"),
            "member_since": body.get("member_since", now),
            "created_at": now,
            "updated_at": now,
        }

        # Add optional fields
        if "address" in body:
            customer["address"] = body["address"]
        if "preferences" in body:
            customer["preferences"] = body["preferences"]
        if "account_last4" in body:
            customer["account_last4"] = body["account_last4"]
        if "recent_transaction" in body:
            customer["recent_transaction"] = body["recent_transaction"]

        customers_table.put_item(Item=customer)

        return create_response(201, customer)

    except Exception as e:
        print(f"Error creating customer: {str(e)}")
        return create_response(
            500, {"error": "Failed to create customer", "message": str(e)}
        )


def handle_update_customer(event: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing customer."""
    path_params = event.get("pathParameters") or {}
    customer_id = path_params.get("customerId")

    if not customer_id:
        return create_response(400, {"error": "Missing customer ID"})

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    try:
        # First, get the existing customer to find the phone (sort key)
        response = customers_table.scan(
            FilterExpression=Attr("customer_id").eq(customer_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Customer not found"})

        existing = items[0]
        phone = existing["phone"]

        # Build update expression
        update_expr = ["updated_at = :updated_at"]
        expr_values = {":updated_at": datetime.now().isoformat()}

        allowed_fields = [
            "email",
            "first_name",
            "last_name",
            "account_type",
            "account_status",
            "address",
            "preferences",
            "account_last4",
            "recent_transaction",
        ]

        for field in allowed_fields:
            if field in body:
                update_expr.append(f"{field} = :{field}")
                expr_values[f":{field}"] = body[field]

        # Update the item
        customers_table.update_item(
            Key={"customer_id": customer_id, "phone": phone},
            UpdateExpression="SET " + ", ".join(update_expr),
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )

        # Get updated customer
        response = customers_table.scan(
            FilterExpression=Attr("customer_id").eq(customer_id)
        )

        return create_response(200, response["Items"][0])

    except Exception as e:
        print(f"Error updating customer: {str(e)}")
        return create_response(
            500, {"error": "Failed to update customer", "message": str(e)}
        )


def handle_get_customer_cases(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get all cases for a customer."""
    path_params = event.get("pathParameters") or {}
    customer_id = path_params.get("customerId")

    if not customer_id:
        return create_response(400, {"error": "Missing customer ID"})

    try:
        params = event.get("queryStringParameters") or {}
        status_filter = params.get("status")

        # Build query
        key_condition = Key("customer_id").eq(customer_id)

        query_params = {
            "IndexName": "customer-index",
            "KeyConditionExpression": key_condition,
            "ScanIndexForward": False,  # Most recent first
        }

        if status_filter:
            query_params["FilterExpression"] = Attr("status").eq(status_filter)

        response = cases_table.query(**query_params)

        return create_response(200, response.get("Items", []))

    except Exception as e:
        print(f"Error getting customer cases: {str(e)}")
        return create_response(
            500, {"error": "Failed to get customer cases", "message": str(e)}
        )


def handle_get_customer_interactions(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get all interactions for a customer."""
    path_params = event.get("pathParameters") or {}
    customer_id = path_params.get("customerId")

    if not customer_id:
        return create_response(400, {"error": "Missing customer ID"})

    try:
        response = interactions_table.query(
            IndexName="customer-index",
            KeyConditionExpression=Key("customer_id").eq(customer_id),
            ScanIndexForward=False,  # Most recent first
        )

        return create_response(200, response.get("Items", []))

    except Exception as e:
        print(f"Error getting customer interactions: {str(e)}")
        return create_response(
            500, {"error": "Failed to get customer interactions", "message": str(e)}
        )


# ==========================================
# Case Handlers
# ==========================================


def handle_get_cases(event: Dict[str, Any]) -> Dict[str, Any]:
    """List cases with optional filters."""
    params = event.get("queryStringParameters") or {}

    try:
        # Filter by customer
        if "customer_id" in params:
            return handle_get_customer_cases(
                {
                    "pathParameters": {"customerId": params["customer_id"]},
                    "queryStringParameters": params,
                }
            )

        # Filter by status
        if "status" in params:
            response = cases_table.query(
                IndexName="status-index",
                KeyConditionExpression=Key("status").eq(params["status"]),
                ScanIndexForward=False,
            )
            return create_response(200, response.get("Items", []))

        # List all cases (with limit)
        limit = int(params.get("limit", 50))
        response = cases_table.scan(Limit=limit)
        return create_response(200, response.get("Items", []))

    except Exception as e:
        print(f"Error listing cases: {str(e)}")
        return create_response(
            500, {"error": "Failed to list cases", "message": str(e)}
        )


def handle_get_case(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get a specific case by ID."""
    path_params = event.get("pathParameters") or {}
    case_id = path_params.get("caseId")

    if not case_id:
        return create_response(400, {"error": "Missing case ID"})

    try:
        response = cases_table.scan(FilterExpression=Attr("case_id").eq(case_id))

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Case not found"})

        return create_response(200, items[0])

    except Exception as e:
        print(f"Error getting case: {str(e)}")
        return create_response(500, {"error": "Failed to get case", "message": str(e)})


def handle_create_case(event: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new support case."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    # Validate input
    is_valid, error_message = validate_case_data(body)
    if not is_valid:
        return create_response(400, {"error": error_message})

    try:
        now = datetime.now().isoformat()

        case = {
            "case_id": generate_case_id(),
            "customer_id": body["customer_id"],
            "subject": body["subject"],
            "description": body.get("description", ""),
            "status": body.get("status", "open"),
            "priority": body.get("priority", "medium"),
            "category": body.get("category", "general"),
            "assigned_to": body.get("assigned_to"),
            "created_at": now,
            "updated_at": now,
            "notes": body.get("notes", []),
        }

        if "session_id" in body:
            case["session_id"] = body["session_id"]

        cases_table.put_item(Item=case)

        return create_response(201, case)

    except Exception as e:
        print(f"Error creating case: {str(e)}")
        return create_response(
            500, {"error": "Failed to create case", "message": str(e)}
        )


def handle_update_case(event: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing case."""
    path_params = event.get("pathParameters") or {}
    case_id = path_params.get("caseId")

    if not case_id:
        return create_response(400, {"error": "Missing case ID"})

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    try:
        # Get existing case
        response = cases_table.scan(FilterExpression=Attr("case_id").eq(case_id))

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Case not found"})

        existing = items[0]
        customer_id = existing["customer_id"]

        # Build update expression
        update_expr = ["updated_at = :updated_at"]
        expr_values = {":updated_at": datetime.now().isoformat()}

        allowed_fields = [
            "subject",
            "description",
            "status",
            "priority",
            "category",
            "assigned_to",
            "resolved_at",
        ]

        for field in allowed_fields:
            if field in body:
                update_expr.append(f"{field} = :{field}")
                expr_values[f":{field}"] = body[field]

        # Update the item
        cases_table.update_item(
            Key={"case_id": case_id, "customer_id": customer_id},
            UpdateExpression="SET " + ", ".join(update_expr),
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )

        # Get updated case
        response = cases_table.scan(FilterExpression=Attr("case_id").eq(case_id))

        return create_response(200, response["Items"][0])

    except Exception as e:
        print(f"Error updating case: {str(e)}")
        return create_response(
            500, {"error": "Failed to update case", "message": str(e)}
        )


def handle_add_case_note(event: Dict[str, Any]) -> Dict[str, Any]:
    """Add a note to an existing case."""
    path_params = event.get("pathParameters") or {}
    case_id = path_params.get("caseId")

    if not case_id:
        return create_response(400, {"error": "Missing case ID"})

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    if "content" not in body or not body["content"]:
        return create_response(400, {"error": "Missing note content"})

    try:
        # Get existing case
        response = cases_table.scan(FilterExpression=Attr("case_id").eq(case_id))

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Case not found"})

        existing = items[0]
        customer_id = existing["customer_id"]

        # Create note
        note = {
            "timestamp": datetime.now().isoformat(),
            "author": body.get("author", "system"),
            "content": body["content"],
        }

        # Append note to list
        cases_table.update_item(
            Key={"case_id": case_id, "customer_id": customer_id},
            UpdateExpression="SET notes = list_append(if_not_exists(notes, :empty_list), :note), updated_at = :updated_at",
            ExpressionAttributeValues={
                ":note": [note],
                ":empty_list": [],
                ":updated_at": datetime.now().isoformat(),
            },
            ReturnValues="ALL_NEW",
        )

        # Get updated case
        response = cases_table.scan(FilterExpression=Attr("case_id").eq(case_id))

        return create_response(200, response["Items"][0])

    except Exception as e:
        print(f"Error adding case note: {str(e)}")
        return create_response(
            500, {"error": "Failed to add case note", "message": str(e)}
        )


# ==========================================
# Interaction Handlers
# ==========================================


def handle_create_interaction(event: Dict[str, Any]) -> Dict[str, Any]:
    """Log a new interaction (call, chat, etc.)."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    if "customer_id" not in body or not body["customer_id"]:
        return create_response(400, {"error": "Missing required field: customer_id"})

    try:
        now = datetime.now().isoformat()

        interaction = {
            "interaction_id": generate_interaction_id(),
            "customer_id": body["customer_id"],
            "session_id": body.get("session_id"),
            "type": body.get("type", "call"),
            "start_time": body.get("start_time", now),
            "duration_seconds": body.get("duration_seconds", 0),
            "status": body.get("status", "completed"),
            "intent": body.get("intent"),
            "sentiment": body.get("sentiment"),
            "resolved": body.get("resolved", False),
            "notes": body.get("notes"),
            "agent_id": body.get("agent_id"),
        }

        interactions_table.put_item(Item=interaction)

        return create_response(201, interaction)

    except Exception as e:
        print(f"Error creating interaction: {str(e)}")
        return create_response(
            500, {"error": "Failed to create interaction", "message": str(e)}
        )


def handle_get_interaction(event: Dict[str, Any]) -> Dict[str, Any]:
    """Get a specific interaction by ID."""
    path_params = event.get("pathParameters") or {}
    interaction_id = path_params.get("interactionId")

    if not interaction_id:
        return create_response(400, {"error": "Missing interaction ID"})

    try:
        response = interactions_table.scan(
            FilterExpression=Attr("interaction_id").eq(interaction_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Interaction not found"})

        return create_response(200, items[0])

    except Exception as e:
        print(f"Error getting interaction: {str(e)}")
        return create_response(
            500, {"error": "Failed to get interaction", "message": str(e)}
        )


def handle_update_interaction(event: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing interaction."""
    path_params = event.get("pathParameters") or {}
    interaction_id = path_params.get("interactionId")

    if not interaction_id:
        return create_response(400, {"error": "Missing interaction ID"})

    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return create_response(400, {"error": "Invalid JSON in request body"})

    try:
        # Get existing interaction
        response = interactions_table.scan(
            FilterExpression=Attr("interaction_id").eq(interaction_id)
        )

        items = response.get("Items", [])
        if not items:
            return create_response(404, {"error": "Interaction not found"})

        existing = items[0]
        customer_id = existing["customer_id"]

        # Build update expression
        update_expr = []
        expr_values = {}

        allowed_fields = [
            "duration_seconds",
            "status",
            "intent",
            "sentiment",
            "resolved",
            "notes",
            "agent_id",
        ]

        for field in allowed_fields:
            if field in body:
                update_expr.append(f"{field} = :{field}")
                expr_values[f":{field}"] = body[field]

        if not update_expr:
            return create_response(400, {"error": "No fields to update"})

        # Update the item
        interactions_table.update_item(
            Key={"interaction_id": interaction_id, "customer_id": customer_id},
            UpdateExpression="SET " + ", ".join(update_expr),
            ExpressionAttributeValues=expr_values,
            ReturnValues="ALL_NEW",
        )

        # Get updated interaction
        response = interactions_table.scan(
            FilterExpression=Attr("interaction_id").eq(interaction_id)
        )

        return create_response(200, response["Items"][0])

    except Exception as e:
        print(f"Error updating interaction: {str(e)}")
        return create_response(
            500, {"error": "Failed to update interaction", "message": str(e)}
        )


# ==========================================
# Admin Handlers (Demo Data)
# ==========================================


def handle_seed_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """Load demo data for testing."""
    try:
        now = datetime.now().isoformat()

        # Demo customers
        demo_customers = [
            {
                "customer_id": "cust-001",
                "phone": "555-0100",
                "email": "john.smith@example.com",
                "first_name": "John",
                "last_name": "Smith",
                "account_type": "premium",
                "account_status": "active",
                "member_since": "2022-03-15T00:00:00Z",
                "created_at": "2022-03-15T00:00:00Z",
                "updated_at": now,
                "account_last4": "4567",
                "recent_transaction": {
                    "date": "2026-01-28",
                    "amount": Decimal("89.99"),
                    "merchant": "TechStore Online",
                },
                "address": {
                    "street": "123 Main St",
                    "city": "Springfield",
                    "state": "IL",
                    "zip": "62701",
                },
            },
            {
                "customer_id": "cust-002",
                "phone": "555-0101",
                "email": "sarah.johnson@example.com",
                "first_name": "Sarah",
                "last_name": "Johnson",
                "account_type": "basic",
                "account_status": "active",
                "member_since": "2024-01-10T00:00:00Z",
                "created_at": "2024-01-10T00:00:00Z",
                "updated_at": now,
                "account_last4": "8901",
                "recent_transaction": {
                    "date": "2026-01-30",
                    "amount": Decimal("45.50"),
                    "merchant": "Coffee Corner",
                },
                "address": {
                    "street": "456 Oak Ave",
                    "city": "Springfield",
                    "state": "IL",
                    "zip": "62702",
                },
            },
            {
                "customer_id": "cust-003",
                "phone": "555-0102",
                "email": "michael.chen@example.com",
                "first_name": "Michael",
                "last_name": "Chen",
                "account_type": "enterprise",
                "account_status": "active",
                "member_since": "2020-11-20T00:00:00Z",
                "created_at": "2020-11-20T00:00:00Z",
                "updated_at": now,
                "account_last4": "2345",
                "recent_transaction": {
                    "date": "2026-01-29",
                    "amount": Decimal("1250.00"),
                    "merchant": "Enterprise Solutions",
                },
                "address": {
                    "street": "789 Business Blvd",
                    "city": "Chicago",
                    "state": "IL",
                    "zip": "60601",
                },
            },
        ]

        # Insert customers
        for customer in demo_customers:
            customers_table.put_item(Item=customer)

        # Demo cases
        demo_cases = [
            {
                "case_id": "TICKET-2026-00001",
                "customer_id": "cust-001",
                "subject": "Billing dispute - October charge",
                "description": "Customer was charged twice for the same service in October",
                "status": "open",
                "priority": "high",
                "category": "billing",
                "created_at": "2026-01-15T10:30:00Z",
                "updated_at": now,
                "notes": [
                    {
                        "timestamp": "2026-01-15T10:30:00Z",
                        "author": "system",
                        "content": "Case created from customer complaint",
                    }
                ],
            },
            {
                "case_id": "TICKET-2026-00002",
                "customer_id": "cust-003",
                "subject": "Service outage - API connectivity",
                "description": "Enterprise customer experiencing intermittent API connectivity issues",
                "status": "in_progress",
                "priority": "urgent",
                "category": "technical",
                "assigned_to": "tech-team-lead",
                "created_at": "2026-01-28T14:00:00Z",
                "updated_at": now,
                "notes": [
                    {
                        "timestamp": "2026-01-28T14:00:00Z",
                        "author": "system",
                        "content": "Urgent case created - enterprise customer affected",
                    },
                    {
                        "timestamp": "2026-01-28T15:30:00Z",
                        "author": "tech-team-lead",
                        "content": "Investigating network connectivity from customer location",
                    },
                ],
            },
        ]

        # Insert cases
        for case in demo_cases:
            cases_table.put_item(Item=case)

        return create_response(
            200,
            {
                "message": "Demo data seeded successfully",
                "customers_seeded": len(demo_customers),
                "cases_seeded": len(demo_cases),
            },
        )

    except Exception as e:
        print(f"Error seeding demo data: {str(e)}")
        return create_response(
            500, {"error": "Failed to seed demo data", "message": str(e)}
        )


def handle_reset_data(event: Dict[str, Any]) -> Dict[str, Any]:
    """Clear all data (use with caution!)."""
    try:
        # Scan and delete all customers
        customers_response = customers_table.scan()
        for item in customers_response.get("Items", []):
            customers_table.delete_item(
                Key={"customer_id": item["customer_id"], "phone": item["phone"]}
            )

        # Scan and delete all cases
        cases_response = cases_table.scan()
        for item in cases_response.get("Items", []):
            cases_table.delete_item(
                Key={"case_id": item["case_id"], "customer_id": item["customer_id"]}
            )

        # Scan and delete all interactions
        interactions_response = interactions_table.scan()
        for item in interactions_response.get("Items", []):
            interactions_table.delete_item(
                Key={
                    "interaction_id": item["interaction_id"],
                    "customer_id": item["customer_id"],
                }
            )

        return create_response(
            200,
            {
                "message": "All data cleared successfully",
                "customers_deleted": len(customers_response.get("Items", [])),
                "cases_deleted": len(cases_response.get("Items", [])),
                "interactions_deleted": len(interactions_response.get("Items", [])),
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
        # Customers endpoints
        if path == "/customers":
            if http_method == "GET":
                return handle_get_customers(event)
            elif http_method == "POST":
                return handle_create_customer(event)

        elif path.startswith("/customers/"):
            parts = path.split("/")
            if len(parts) >= 3:
                customer_id = parts[2]

                # /customers/{id}/cases
                if len(parts) == 4 and parts[3] == "cases":
                    return handle_get_customer_cases(event)

                # /customers/{id}/interactions
                elif len(parts) == 4 and parts[3] == "interactions":
                    return handle_get_customer_interactions(event)

                # /customers/{id}
                elif len(parts) == 3:
                    if http_method == "GET":
                        return handle_get_customer(event)
                    elif http_method == "PUT":
                        return handle_update_customer(event)

        # Cases endpoints
        elif path == "/cases":
            if http_method == "GET":
                return handle_get_cases(event)
            elif http_method == "POST":
                return handle_create_case(event)

        elif path.startswith("/cases/"):
            parts = path.split("/")
            if len(parts) >= 3:
                case_id = parts[2]

                # /cases/{id}/notes
                if len(parts) == 4 and parts[3] == "notes":
                    return handle_add_case_note(event)

                # /cases/{id}
                elif len(parts) == 3:
                    if http_method == "GET":
                        return handle_get_case(event)
                    elif http_method == "PUT":
                        return handle_update_case(event)

        # Interactions endpoints
        elif path == "/interactions":
            if http_method == "POST":
                return handle_create_interaction(event)

        elif path.startswith("/interactions/"):
            parts = path.split("/")
            if len(parts) == 3:
                interaction_id = parts[2]
                if http_method == "GET":
                    return handle_get_interaction(event)
                elif http_method == "PUT":
                    return handle_update_interaction(event)

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
                        "customers": customers_table_name,
                        "cases": cases_table_name,
                        "interactions": interactions_table_name,
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
