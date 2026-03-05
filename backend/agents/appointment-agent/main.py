#!/usr/bin/env python3
"""Appointment Scheduling Capability Agent.

A standalone Strands A2A agent that provides appointment scheduling capabilities
via the A2A protocol. Deployed as an independent ECS Fargate service, discovered
by the voice agent via CloudMap.

The agent wraps 5 appointment tools behind Strands @tool decorators and exposes
them via A2AServer. The voice agent's LLM sees the tool descriptions (from @tool
docstrings) and invokes them over A2A when appropriate.

Tools provided:
    - check_availability: Check open time slots for a date and service type
    - book_appointment: Book a new appointment for a customer
    - get_appointment: Retrieve appointment details by ID
    - cancel_appointment: Cancel an existing appointment
    - reschedule_appointment: Move an appointment to a new date/time

Environment variables:
    APPOINTMENT_API_URL: Base URL for the Appointment REST API (required)
    AWS_REGION: AWS region (default: us-east-1)
    LLM_MODEL_ID: Bedrock model for agent reasoning
        (default: us.anthropic.claude-haiku-4-5-20251001-v1:0)
    PORT: Server port (default: 8000)
    AGENT_NAME: Agent name for logging (default: appointment)
"""

import os
import sys
import time

import requests
import structlog
from a2a.types import AgentSkill
from appointment_client import AppointmentClient, AppointmentError
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

# Configuration from environment
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
APPOINTMENT_API_URL = os.getenv("APPOINTMENT_API_URL", "")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
PORT = int(os.getenv("PORT", "8000"))

# Shared client instance (initialized lazily)
_appointment_client = None


def _get_task_private_ip() -> str | None:
    """Get this ECS task's private IPv4 address from the metadata endpoint.

    In ECS Fargate, the metadata endpoint provides task network info.
    We use this so the Agent Card advertises a reachable URL instead of 0.0.0.0.

    Returns:
        Private IP string, or None if not running in ECS.
    """
    metadata_uri = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
    if not metadata_uri:
        return None

    try:
        resp = requests.get(f"{metadata_uri}/task", timeout=2)
        resp.raise_for_status()
        task_meta = resp.json()
        containers = task_meta.get("Containers", [])
        for container in containers:
            networks = container.get("Networks", [])
            for network in networks:
                addrs = network.get("IPv4Addresses", [])
                if addrs:
                    return addrs[0]
    except Exception as e:
        logger.warning("task_ip_metadata_failed", error=str(e))

    return None


def _get_appointment_client() -> AppointmentClient:
    """Lazy-initialize the Appointment client."""
    global _appointment_client
    if _appointment_client is None:
        _appointment_client = AppointmentClient(base_url=APPOINTMENT_API_URL)
    return _appointment_client


# =============================================================================
# Tool: check_availability
# =============================================================================


@tool
def check_availability(date: str, service_type: str = "general_consultation") -> dict:
    """Check available appointment time slots for a specific date and service
    type. Use this tool when a customer wants to schedule an appointment and
    you need to find open slots. Returns the available time windows and
    service duration. Business hours are 9AM to 5PM on weekdays.

    Args:
        date: The date to check availability for, in YYYY-MM-DD format (e.g., '2026-03-10').
        service_type: The type of service appointment. Options: 'on_site_repair' (60 min), 'network_setup' (90 min), 'hardware_upgrade' (120 min), 'general_consultation' (30 min), 'preventive_maintenance' (45 min). Default: 'general_consultation'.

    Returns:
        Dictionary with date, service info, available time slots, and total count.
    """
    if not date or not date.strip():
        return {"error": "Date is required (YYYY-MM-DD format)"}

    date = date.strip()
    service_type = (service_type or "general_consultation").strip()

    tool_start = time.monotonic()

    try:
        client = _get_appointment_client()

        if not client.is_configured():
            return {"error": "Appointment service is not configured"}

        result = client.check_availability(date, service_type)
        total_ms = (time.monotonic() - tool_start) * 1000

        logger.info(
            "availability_check_complete",
            date=date,
            service_type=service_type,
            slots_available=result.get("total_available", 0),
            total_ms=round(total_ms, 1),
        )

        # Add a helpful message for the agent
        total = result.get("total_available", 0)
        if total > 0:
            slots = result.get("available_slots", [])
            sample = slots[:5]
            slot_strs = [f"{s['start_time']}-{s['end_time']}" for s in sample]
            more = f" (and {total - 5} more)" if total > 5 else ""
            result["message"] = (
                f"{total} time slot(s) available on {date} for "
                f"{result.get('service_label', service_type)} "
                f"({result.get('duration_minutes', '?')} min): "
                f"{', '.join(slot_strs)}{more}"
            )
        else:
            result["message"] = (
                f"No time slots available on {date} for "
                f"{result.get('service_label', service_type)}. "
                f"Please try a different date."
            )

        return result

    except AppointmentError as e:
        logger.error("appointment_error_check_availability", error=e.message)
        return {"error": f"Appointment error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_check_availability")
        return {"error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: book_appointment
# =============================================================================


@tool
def book_appointment(
    customer_id: str,
    date: str,
    start_time: str,
    service_type: str,
    notes: str = "",
) -> dict:
    """Book a new appointment for a customer at a specific date and time.
    Use this tool after checking availability and confirming the slot with
    the customer. The appointment will be confirmed immediately.

    Args:
        customer_id: The customer's unique ID (from CRM lookup).
        date: Appointment date in YYYY-MM-DD format (e.g., '2026-03-10').
        start_time: Start time in HH:MM format (e.g., '10:00'). Must be during business hours (9:00-17:00).
        service_type: Service type: 'on_site_repair', 'network_setup', 'hardware_upgrade', 'general_consultation', or 'preventive_maintenance'.
        notes: Optional notes about the appointment (e.g., 'Customer prefers morning').

    Returns:
        Dictionary with the booked appointment details and confirmation.
    """
    if not customer_id or not customer_id.strip():
        return {"booked": False, "error": "Customer ID is required"}
    if not date or not date.strip():
        return {"booked": False, "error": "Date is required (YYYY-MM-DD)"}
    if not start_time or not start_time.strip():
        return {"booked": False, "error": "Start time is required (HH:MM)"}
    if not service_type or not service_type.strip():
        return {"booked": False, "error": "Service type is required"}

    customer_id = customer_id.strip()
    date = date.strip()
    start_time = start_time.strip()
    service_type = service_type.strip()
    notes = (notes or "").strip()

    valid_types = [
        "on_site_repair",
        "network_setup",
        "hardware_upgrade",
        "general_consultation",
        "preventive_maintenance",
    ]
    if service_type not in valid_types:
        return {
            "booked": False,
            "error": f"Invalid service_type '{service_type}'. Must be one of: {', '.join(valid_types)}",
        }

    tool_start = time.monotonic()

    try:
        client = _get_appointment_client()

        if not client.is_configured():
            return {"booked": False, "error": "Appointment service is not configured"}

        appt = client.book_appointment(
            customer_id=customer_id,
            date=date,
            start_time=start_time,
            service_type=service_type,
            notes=notes,
        )
        total_ms = (time.monotonic() - tool_start) * 1000

        logger.info(
            "appointment_booked",
            appointment_id=appt.appointment_id,
            total_ms=round(total_ms, 1),
        )

        return {
            "booked": True,
            "appointment": appt.to_dict(),
            "message": (
                f"Appointment {appt.appointment_id} confirmed for {appt.appointment_date} "
                f"at {appt.start_time}-{appt.end_time} ({appt.service_label}). "
                f"Duration: {appt.duration_minutes} minutes."
            ),
        }

    except AppointmentError as e:
        logger.error("appointment_error_book", error=e.message, error_code=e.error_code)
        if e.error_code == "APPOINTMENT_CONFLICT":
            return {
                "booked": False,
                "error": e.message,
                "message": "That time slot is no longer available. Please check availability again.",
            }
        return {"booked": False, "error": f"Appointment error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_book_appointment")
        return {"booked": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: get_appointment
# =============================================================================


@tool
def get_appointment(appointment_id: str) -> dict:
    """Retrieve the details of an existing appointment by its ID. Use this
    tool when a customer asks about a specific appointment or you need to
    look up appointment details before making changes.

    Args:
        appointment_id: The appointment ID (e.g., 'APPT-2026-ABC123').

    Returns:
        Dictionary with appointment details, or not-found message.
    """
    if not appointment_id or not appointment_id.strip():
        return {"found": False, "error": "Appointment ID is required"}

    appointment_id = appointment_id.strip()

    try:
        client = _get_appointment_client()

        if not client.is_configured():
            return {"found": False, "error": "Appointment service is not configured"}

        appt = client.get_appointment(appointment_id)

        if not appt:
            return {
                "found": False,
                "appointment_id": appointment_id,
                "message": f"No appointment found with ID {appointment_id}",
            }

        return {
            "found": True,
            "appointment": appt.to_dict(),
            "message": (
                f"Appointment {appt.appointment_id}: {appt.service_label} on "
                f"{appt.appointment_date} at {appt.start_time}-{appt.end_time}. "
                f"Status: {appt.status}."
            ),
        }

    except AppointmentError as e:
        logger.error("appointment_error_get", error=e.message)
        return {"found": False, "error": f"Appointment error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_get_appointment")
        return {"found": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: cancel_appointment
# =============================================================================


@tool
def cancel_appointment(
    appointment_id: str, reason: str = "Cancelled by caller"
) -> dict:
    """Cancel an existing appointment. Use this tool when a customer wants to
    cancel their scheduled appointment. Always confirm with the customer
    before cancelling. The cancellation is immediate and the time slot becomes
    available for others.

    Args:
        appointment_id: The appointment ID to cancel (e.g., 'APPT-2026-ABC123').
        reason: Reason for cancellation (e.g., 'Customer no longer needs service').

    Returns:
        Dictionary with cancellation confirmation and updated appointment details.
    """
    if not appointment_id or not appointment_id.strip():
        return {"cancelled": False, "error": "Appointment ID is required"}

    appointment_id = appointment_id.strip()
    reason = (reason or "Cancelled by caller").strip()

    try:
        client = _get_appointment_client()

        if not client.is_configured():
            return {
                "cancelled": False,
                "error": "Appointment service is not configured",
            }

        appt = client.cancel_appointment(appointment_id, reason)

        logger.info("appointment_cancelled", appointment_id=appointment_id)

        return {
            "cancelled": True,
            "appointment": appt.to_dict(),
            "message": (
                f"Appointment {appt.appointment_id} has been cancelled. "
                f"It was originally scheduled for {appt.appointment_date} "
                f"at {appt.start_time} ({appt.service_label})."
            ),
        }

    except AppointmentError as e:
        logger.error(
            "appointment_error_cancel", error=e.message, error_code=e.error_code
        )
        if e.error_code == "APPOINTMENT_NOT_FOUND":
            return {
                "cancelled": False,
                "error": "Appointment not found",
                "appointment_id": appointment_id,
            }
        return {"cancelled": False, "error": f"Appointment error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_cancel_appointment")
        return {"cancelled": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: reschedule_appointment
# =============================================================================


@tool
def reschedule_appointment(appointment_id: str, new_date: str, new_time: str) -> dict:
    """Reschedule an existing appointment to a new date and time. Use this tool
    when a customer wants to change their appointment. Check availability first
    to find open slots, then use this tool to move the appointment.

    Args:
        appointment_id: The appointment ID to reschedule (e.g., 'APPT-2026-ABC123').
        new_date: New appointment date in YYYY-MM-DD format.
        new_time: New start time in HH:MM format (must be during business hours 9:00-17:00).

    Returns:
        Dictionary with rescheduling confirmation and updated appointment details.
    """
    if not appointment_id or not appointment_id.strip():
        return {"rescheduled": False, "error": "Appointment ID is required"}
    if not new_date or not new_date.strip():
        return {"rescheduled": False, "error": "New date is required (YYYY-MM-DD)"}
    if not new_time or not new_time.strip():
        return {"rescheduled": False, "error": "New time is required (HH:MM)"}

    appointment_id = appointment_id.strip()
    new_date = new_date.strip()
    new_time = new_time.strip()

    try:
        client = _get_appointment_client()

        if not client.is_configured():
            return {
                "rescheduled": False,
                "error": "Appointment service is not configured",
            }

        appt = client.reschedule_appointment(appointment_id, new_date, new_time)

        logger.info(
            "appointment_rescheduled",
            appointment_id=appointment_id,
            new_date=new_date,
            new_time=new_time,
        )

        msg = (
            f"Appointment {appt.appointment_id} has been rescheduled to "
            f"{appt.appointment_date} at {appt.start_time}-{appt.end_time} "
            f"({appt.service_label})."
        )
        if appt.previous_date:
            msg += f" Previously: {appt.previous_date} at {appt.previous_time}."

        return {
            "rescheduled": True,
            "appointment": appt.to_dict(),
            "message": msg,
        }

    except AppointmentError as e:
        logger.error(
            "appointment_error_reschedule", error=e.message, error_code=e.error_code
        )
        if e.error_code == "APPOINTMENT_NOT_FOUND":
            return {
                "rescheduled": False,
                "error": "Appointment not found",
                "appointment_id": appointment_id,
            }
        if e.error_code == "APPOINTMENT_CONFLICT":
            return {
                "rescheduled": False,
                "error": e.message,
                "message": "That time slot is not available. Please check availability and try a different slot.",
            }
        return {"rescheduled": False, "error": f"Appointment error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_reschedule_appointment")
        return {"rescheduled": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Agent setup and server
# =============================================================================


def main():
    """Start the Appointment A2A agent server."""
    if not APPOINTMENT_API_URL:
        logger.warning(
            "appointment_api_url_not_set",
            note="agent will return errors for appointment operations",
        )

    # --- Warm-up: pre-initialize Appointment client to reuse TCP connections ---
    warmup_start = time.monotonic()
    try:
        _get_appointment_client()
        logger.info(
            "appointment_client_warmup_complete",
            elapsed_ms=round((time.monotonic() - warmup_start) * 1000, 1),
        )
    except Exception as e:
        logger.warning("appointment_client_warmup_failed", error=str(e))

    model = BedrockModel(
        model_id=LLM_MODEL_ID,
        region_name=AWS_REGION,
    )

    agent = Agent(
        name="Appointment Agent",
        description=(
            "Appointment scheduling: check available time slots, book new appointments, "
            "retrieve appointment details, cancel appointments, and reschedule existing "
            "appointments. Supports service types including on-site repair, network setup, "
            "hardware upgrade, general consultation, and preventive maintenance. "
            "Business hours are 9AM-5PM weekdays. "
            "IMPORTANT: A customer_id is required to book, cancel, or reschedule "
            "appointments. The customer must be identified through the CRM system "
            "before scheduling actions can be performed."
        ),
        model=model,
        tools=[
            check_availability,
            book_appointment,
            get_appointment,
            cancel_appointment,
            reschedule_appointment,
        ],
        callback_handler=None,
    )

    # --- Warm-up: probe the Strands agent to force BedrockModel initialization ---
    agent_warmup_start = time.monotonic()
    try:
        agent("warmup")
        logger.info(
            "strands_agent_warmup_complete",
            elapsed_ms=round((time.monotonic() - agent_warmup_start) * 1000, 1),
        )
    except Exception as e:
        logger.warning(
            "strands_agent_warmup_failed",
            error=str(e),
            note="will initialize on first real call",
        )

    # Determine the reachable URL for the Agent Card.
    task_ip = _get_task_private_ip()
    http_url = f"http://{task_ip}:{PORT}/" if task_ip else None

    # Explicit skill definitions with provides/requires tags for dependency
    # gating. The voice agent's flow system reads these tags to enforce
    # prerequisites (e.g., booking requires customer_id from CRM lookup).
    skills = [
        AgentSkill(
            id="check_availability",
            name="check_availability",
            description=(
                "Check available appointment time slots for a specific date "
                "and service type. Business hours 9AM-5PM weekdays."
            ),
            tags=[],  # No requirements -- anyone can check availability
        ),
        AgentSkill(
            id="book_appointment",
            name="book_appointment",
            description="Book a new appointment for a customer.",
            tags=["requires:customer_id"],
        ),
        AgentSkill(
            id="get_appointment",
            name="get_appointment",
            description="Retrieve appointment details by appointment ID.",
            tags=[],
        ),
        AgentSkill(
            id="cancel_appointment",
            name="cancel_appointment",
            description="Cancel an existing appointment.",
            tags=["requires:customer_id"],
        ),
        AgentSkill(
            id="reschedule_appointment",
            name="reschedule_appointment",
            description="Move an appointment to a new date and time.",
            tags=["requires:customer_id"],
        ),
    ]

    server = A2AServer(
        agent=agent,
        host="0.0.0.0",
        port=PORT,
        http_url=http_url,
        version="0.1.0",
        skills=skills,
    )

    logger.info("appointment_agent_starting", port=PORT)
    logger.info(
        "appointment_config",
        appointment_api_url=APPOINTMENT_API_URL or "(not configured)",
    )
    logger.info("appointment_model", model_id=LLM_MODEL_ID)
    logger.info("agent_card_url", url=http_url or f"http://0.0.0.0:{PORT}/")
    # Disable uvicorn access logs -- CloudMap polls /.well-known/agent-card.json
    # every 30s, producing ~2,880 noise lines/day.
    server.serve(access_log=False)


if __name__ == "__main__":
    main()
