"""Tests for Appointment agent tools (main.py @tool functions).

Each tool is tested in isolation by mocking the Appointment client. The tools are
plain functions decorated with @tool — we call them directly.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# The agent's main.py uses `from appointment_client import ...` (no package prefix).
# To make that import work in tests, we add the agent source directory to the path.
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from appointment_client import AppointmentClient, AppointmentError, Appointment  # noqa: E402

# We need to import the tool functions. main.py reads env vars and sets up
# module-level globals. We patch them before importing.
with patch.dict(
    "os.environ",
    {
        "APPOINTMENT_API_URL": "http://fake-appointment/",
        "AWS_REGION": "us-east-1",
    },
):
    from main import (  # noqa: E402
        check_availability,
        book_appointment,
        get_appointment,
        cancel_appointment,
        reschedule_appointment,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_APPOINTMENT = Appointment(
    appointment_id="APPT-2026-ABC123",
    customer_id="CUST-001",
    appointment_date="2026-03-10",
    start_time="10:00",
    end_time="10:30",
    service_type="general_consultation",
    service_label="General Consultation",
    duration_minutes=30,
    status="confirmed",
    notes="Customer prefers morning",
    created_at="2026-03-04T10:00:00Z",
    updated_at="2026-03-04T10:00:00Z",
)

SAMPLE_CANCELLED_APPOINTMENT = Appointment(
    appointment_id="APPT-2026-ABC123",
    customer_id="CUST-001",
    appointment_date="2026-03-10",
    start_time="10:00",
    end_time="10:30",
    service_type="general_consultation",
    service_label="General Consultation",
    duration_minutes=30,
    status="cancelled",
    notes="",
    created_at="2026-03-04T10:00:00Z",
    updated_at="2026-03-04T11:00:00Z",
    cancellation_reason="Customer request",
    cancelled_at="2026-03-04T11:00:00Z",
)

SAMPLE_RESCHEDULED_APPOINTMENT = Appointment(
    appointment_id="APPT-2026-ABC123",
    customer_id="CUST-001",
    appointment_date="2026-03-12",
    start_time="14:00",
    end_time="14:30",
    service_type="general_consultation",
    service_label="General Consultation",
    duration_minutes=30,
    status="confirmed",
    notes="",
    created_at="2026-03-04T10:00:00Z",
    updated_at="2026-03-04T12:00:00Z",
    previous_date="2026-03-10",
    previous_time="10:00",
)


@pytest.fixture(autouse=True)
def mock_appointment_client():
    """Replace the global Appointment client with a mock for every test."""
    mock = MagicMock(spec=AppointmentClient)
    mock.is_configured.return_value = True
    with (
        patch("main._appointment_client", mock),
        patch("main._get_appointment_client", return_value=mock),
    ):
        yield mock


# ---------------------------------------------------------------------------
# check_availability
# ---------------------------------------------------------------------------


class TestCheckAvailability:
    def test_slots_available(self, mock_appointment_client):
        mock_appointment_client.check_availability.return_value = {
            "date": "2026-03-10",
            "service_type": "general_consultation",
            "service_label": "General Consultation",
            "duration_minutes": 30,
            "available_slots": [
                {"start_time": "09:00", "end_time": "09:30"},
                {"start_time": "09:30", "end_time": "10:00"},
                {"start_time": "10:00", "end_time": "10:30"},
            ],
            "total_available": 3,
        }

        result = check_availability(
            date="2026-03-10", service_type="general_consultation"
        )

        assert "error" not in result
        assert result["total_available"] == 3
        assert "3 time slot(s)" in result["message"]

    def test_no_slots_available(self, mock_appointment_client):
        mock_appointment_client.check_availability.return_value = {
            "date": "2026-03-10",
            "service_type": "general_consultation",
            "service_label": "General Consultation",
            "duration_minutes": 30,
            "available_slots": [],
            "total_available": 0,
        }

        result = check_availability(date="2026-03-10")

        assert result["total_available"] == 0
        assert "No time slots" in result["message"]

    def test_empty_date(self):
        result = check_availability(date="")
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_whitespace_date(self):
        result = check_availability(date="   ")
        assert "error" in result

    def test_not_configured(self, mock_appointment_client):
        mock_appointment_client.is_configured.return_value = False

        result = check_availability(date="2026-03-10")

        assert "error" in result
        assert "not configured" in result["error"].lower()

    def test_api_error(self, mock_appointment_client):
        mock_appointment_client.check_availability.side_effect = AppointmentError(
            "timeout"
        )

        result = check_availability(date="2026-03-10")

        assert "error" in result
        assert "Appointment error" in result["error"]

    def test_many_slots_truncated_message(self, mock_appointment_client):
        slots = [
            {
                "start_time": f"{9 + i // 2:02d}:{(i % 2) * 30:02d}",
                "end_time": f"{9 + (i + 1) // 2:02d}:{((i + 1) % 2) * 30:02d}",
            }
            for i in range(10)
        ]
        mock_appointment_client.check_availability.return_value = {
            "date": "2026-03-10",
            "service_type": "general_consultation",
            "service_label": "General Consultation",
            "duration_minutes": 30,
            "available_slots": slots,
            "total_available": 10,
        }

        result = check_availability(date="2026-03-10")

        assert "and 5 more" in result["message"]


# ---------------------------------------------------------------------------
# book_appointment
# ---------------------------------------------------------------------------


class TestBookAppointment:
    def test_success(self, mock_appointment_client):
        mock_appointment_client.book_appointment.return_value = SAMPLE_APPOINTMENT

        result = book_appointment(
            customer_id="CUST-001",
            date="2026-03-10",
            start_time="10:00",
            service_type="general_consultation",
            notes="Prefers morning",
        )

        assert result["booked"] is True
        assert result["appointment"]["appointment_id"] == "APPT-2026-ABC123"
        assert "confirmed" in result["message"].lower()

    def test_missing_customer_id(self):
        result = book_appointment(
            customer_id="",
            date="2026-03-10",
            start_time="10:00",
            service_type="general_consultation",
        )
        assert result["booked"] is False
        assert "required" in result["error"].lower()

    def test_missing_date(self):
        result = book_appointment(
            customer_id="CUST-001",
            date="",
            start_time="10:00",
            service_type="general_consultation",
        )
        assert result["booked"] is False

    def test_missing_start_time(self):
        result = book_appointment(
            customer_id="CUST-001",
            date="2026-03-10",
            start_time="",
            service_type="general_consultation",
        )
        assert result["booked"] is False

    def test_missing_service_type(self):
        result = book_appointment(
            customer_id="CUST-001",
            date="2026-03-10",
            start_time="10:00",
            service_type="",
        )
        assert result["booked"] is False

    def test_invalid_service_type(self):
        result = book_appointment(
            customer_id="CUST-001",
            date="2026-03-10",
            start_time="10:00",
            service_type="invalid_service",
        )
        assert result["booked"] is False
        assert "Invalid service_type" in result["error"]

    def test_conflict(self, mock_appointment_client):
        mock_appointment_client.book_appointment.side_effect = AppointmentError(
            "Time slot conflict", error_code="APPOINTMENT_CONFLICT"
        )

        result = book_appointment(
            customer_id="CUST-001",
            date="2026-03-10",
            start_time="10:00",
            service_type="general_consultation",
        )

        assert result["booked"] is False
        assert "no longer available" in result["message"].lower()

    def test_not_configured(self, mock_appointment_client):
        mock_appointment_client.is_configured.return_value = False

        result = book_appointment(
            customer_id="CUST-001",
            date="2026-03-10",
            start_time="10:00",
            service_type="general_consultation",
        )

        assert result["booked"] is False
        assert "not configured" in result["error"].lower()


# ---------------------------------------------------------------------------
# get_appointment
# ---------------------------------------------------------------------------


class TestGetAppointment:
    def test_found(self, mock_appointment_client):
        mock_appointment_client.get_appointment.return_value = SAMPLE_APPOINTMENT

        result = get_appointment(appointment_id="APPT-2026-ABC123")

        assert result["found"] is True
        assert result["appointment"]["appointment_id"] == "APPT-2026-ABC123"
        assert "General Consultation" in result["message"]

    def test_not_found(self, mock_appointment_client):
        mock_appointment_client.get_appointment.return_value = None

        result = get_appointment(appointment_id="APPT-2026-UNKNOWN")

        assert result["found"] is False
        assert "No appointment found" in result["message"]

    def test_empty_id(self):
        result = get_appointment(appointment_id="")
        assert result["found"] is False
        assert "required" in result["error"].lower()

    def test_api_error(self, mock_appointment_client):
        mock_appointment_client.get_appointment.side_effect = AppointmentError("fail")

        result = get_appointment(appointment_id="APPT-2026-ABC123")

        assert result["found"] is False
        assert "Appointment error" in result["error"]


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


class TestCancelAppointment:
    def test_success(self, mock_appointment_client):
        mock_appointment_client.cancel_appointment.return_value = (
            SAMPLE_CANCELLED_APPOINTMENT
        )

        result = cancel_appointment(
            appointment_id="APPT-2026-ABC123", reason="Customer request"
        )

        assert result["cancelled"] is True
        assert "cancelled" in result["message"].lower()

    def test_empty_id(self):
        result = cancel_appointment(appointment_id="")
        assert result["cancelled"] is False
        assert "required" in result["error"].lower()

    def test_not_found(self, mock_appointment_client):
        mock_appointment_client.cancel_appointment.side_effect = AppointmentError(
            "Appointment not found", error_code="APPOINTMENT_NOT_FOUND"
        )

        result = cancel_appointment(appointment_id="APPT-2026-UNKNOWN")

        assert result["cancelled"] is False
        assert "not found" in result["error"].lower()

    def test_not_configured(self, mock_appointment_client):
        mock_appointment_client.is_configured.return_value = False

        result = cancel_appointment(appointment_id="APPT-2026-ABC123")

        assert result["cancelled"] is False


# ---------------------------------------------------------------------------
# reschedule_appointment
# ---------------------------------------------------------------------------


class TestRescheduleAppointment:
    def test_success(self, mock_appointment_client):
        mock_appointment_client.reschedule_appointment.return_value = (
            SAMPLE_RESCHEDULED_APPOINTMENT
        )

        result = reschedule_appointment(
            appointment_id="APPT-2026-ABC123",
            new_date="2026-03-12",
            new_time="14:00",
        )

        assert result["rescheduled"] is True
        assert "rescheduled" in result["message"].lower()
        assert "Previously" in result["message"]

    def test_missing_id(self):
        result = reschedule_appointment(
            appointment_id="", new_date="2026-03-12", new_time="14:00"
        )
        assert result["rescheduled"] is False

    def test_missing_date(self):
        result = reschedule_appointment(
            appointment_id="APPT-2026-ABC123", new_date="", new_time="14:00"
        )
        assert result["rescheduled"] is False

    def test_missing_time(self):
        result = reschedule_appointment(
            appointment_id="APPT-2026-ABC123", new_date="2026-03-12", new_time=""
        )
        assert result["rescheduled"] is False

    def test_conflict(self, mock_appointment_client):
        mock_appointment_client.reschedule_appointment.side_effect = AppointmentError(
            "Time slot conflict on the new date", error_code="APPOINTMENT_CONFLICT"
        )

        result = reschedule_appointment(
            appointment_id="APPT-2026-ABC123",
            new_date="2026-03-12",
            new_time="14:00",
        )

        assert result["rescheduled"] is False
        assert "not available" in result["message"].lower()

    def test_not_found(self, mock_appointment_client):
        mock_appointment_client.reschedule_appointment.side_effect = AppointmentError(
            "Appointment not found", error_code="APPOINTMENT_NOT_FOUND"
        )

        result = reschedule_appointment(
            appointment_id="APPT-2026-UNKNOWN",
            new_date="2026-03-12",
            new_time="14:00",
        )

        assert result["rescheduled"] is False
        assert "not found" in result["error"].lower()
