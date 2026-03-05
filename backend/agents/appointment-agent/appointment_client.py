"""Synchronous Appointment HTTP client for the Appointment capability agent.

Communicates with the Appointment Scheduling REST API (API Gateway + Lambda)
deployed by the AppointmentStack. Uses synchronous `requests` because
Strands @tool functions are synchronous.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
import structlog

logger = structlog.get_logger(__name__)


class AppointmentError(Exception):
    """Exception raised for Appointment API errors."""

    def __init__(self, message: str, error_code: str = "APPOINTMENT_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


@dataclass
class Appointment:
    """Appointment data from the scheduling API."""

    appointment_id: str
    customer_id: str
    appointment_date: str
    start_time: str
    end_time: str
    service_type: str
    service_label: str
    duration_minutes: int
    status: str
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[str] = None
    previous_date: Optional[str] = None
    previous_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "appointment_id": self.appointment_id,
            "customer_id": self.customer_id,
            "appointment_date": self.appointment_date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "service_type": self.service_type,
            "service_label": self.service_label,
            "duration_minutes": self.duration_minutes,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.cancellation_reason:
            result["cancellation_reason"] = self.cancellation_reason
            result["cancelled_at"] = self.cancelled_at
        if self.previous_date:
            result["previous_date"] = self.previous_date
            result["previous_time"] = self.previous_time
        return result


@dataclass
class TimeSlot:
    """An available time slot."""

    start_time: str
    end_time: str

    def to_dict(self) -> Dict[str, str]:
        return {"start_time": self.start_time, "end_time": self.end_time}


class AppointmentClient:
    """Synchronous HTTP client for the Appointment Scheduling API.

    Uses a persistent requests.Session to reuse TCP connections across calls,
    reducing connection setup overhead (~50-100ms per call).

    Example:
        >>> client = AppointmentClient()
        >>> slots = client.check_availability("2026-03-10", "on_site_repair")
        >>> if slots:
        ...     appt = client.book_appointment("CUST-001", "2026-03-10", "09:00", "on_site_repair")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ):
        """Initialize the Appointment client.

        Args:
            base_url: Appointment API base URL (defaults to APPOINTMENT_API_URL env var)
            timeout_seconds: Request timeout in seconds
        """
        self.base_url = base_url or os.environ.get("APPOINTMENT_API_URL", "")
        self.timeout = timeout_seconds
        self._session = requests.Session()

        if not self.base_url:
            logger.warning("appointment_api_url_not_configured")

    def is_configured(self) -> bool:
        """Check if the client is properly configured."""
        return bool(self.base_url)

    def check_availability(
        self, date: str, service_type: str = "general_consultation"
    ) -> Dict[str, Any]:
        """Check available time slots for a date and service type.

        Args:
            date: Date in YYYY-MM-DD format
            service_type: Service type key (e.g., 'on_site_repair')

        Returns:
            Dict with date, service info, and available_slots list

        Raises:
            AppointmentError: If the API request fails
        """
        self._check_configured()

        logger.info("checking_availability", date=date, service_type=service_type)

        try:
            response = self._session.get(
                f"{self.base_url}availability",
                params={"date": date, "service_type": service_type},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                data = self._safe_json(response)
                raise AppointmentError(
                    data.get(
                        "error", f"Failed to check availability: {response.status_code}"
                    ),
                    error_code="AVAILABILITY_CHECK_FAILED",
                )
        except requests.RequestException as e:
            logger.error("appointment_availability_error", error=str(e))
            raise AppointmentError(
                f"Failed to check availability: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def book_appointment(
        self,
        customer_id: str,
        date: str,
        start_time: str,
        service_type: str,
        notes: str = "",
    ) -> Appointment:
        """Book a new appointment.

        Args:
            customer_id: Customer ID
            date: Date in YYYY-MM-DD format
            start_time: Start time in HH:MM format
            service_type: Service type key
            notes: Optional notes

        Returns:
            Created Appointment object

        Raises:
            AppointmentError: If the API request fails or conflict exists
        """
        self._check_configured()

        logger.info(
            "booking_appointment",
            customer_id=customer_id,
            date=date,
            start_time=start_time,
            service_type=service_type,
        )

        try:
            payload = {
                "customer_id": customer_id,
                "date": date,
                "start_time": start_time,
                "service_type": service_type,
                "notes": notes,
            }

            response = self._session.post(
                f"{self.base_url}appointments",
                json=payload,
                timeout=self.timeout,
            )

            if response.status_code == 201:
                return self._parse_appointment(response.json())
            elif response.status_code == 409:
                data = self._safe_json(response)
                raise AppointmentError(
                    data.get("error", "Time slot conflict"),
                    error_code="APPOINTMENT_CONFLICT",
                )
            else:
                data = self._safe_json(response)
                raise AppointmentError(
                    data.get(
                        "error", f"Failed to book appointment: {response.status_code}"
                    ),
                    error_code="APPOINTMENT_BOOK_FAILED",
                )
        except requests.RequestException as e:
            logger.error("appointment_book_error", error=str(e))
            raise AppointmentError(
                f"Failed to book appointment: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def get_appointment(self, appointment_id: str) -> Optional[Appointment]:
        """Get an appointment by ID.

        Args:
            appointment_id: Appointment ID (e.g., 'APPT-2026-ABC123')

        Returns:
            Appointment object if found, None otherwise

        Raises:
            AppointmentError: If the API request fails
        """
        self._check_configured()

        logger.info("getting_appointment", appointment_id=appointment_id)

        try:
            response = self._session.get(
                f"{self.base_url}appointments/{appointment_id}",
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return self._parse_appointment(response.json())
            elif response.status_code == 404:
                return None
            else:
                raise AppointmentError(
                    f"Failed to get appointment: {response.status_code}",
                    error_code="APPOINTMENT_GET_FAILED",
                )
        except requests.RequestException as e:
            logger.error(
                "appointment_get_error", error=str(e), appointment_id=appointment_id
            )
            raise AppointmentError(
                f"Failed to get appointment: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def list_appointments(
        self,
        customer_id: Optional[str] = None,
        date: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Appointment]:
        """List appointments with optional filters.

        Args:
            customer_id: Filter by customer ID
            date: Filter by date (YYYY-MM-DD)
            status: Filter by status (confirmed, cancelled)

        Returns:
            List of Appointment objects

        Raises:
            AppointmentError: If the API request fails
        """
        self._check_configured()

        logger.info(
            "listing_appointments",
            customer_id=customer_id,
            date=date,
            status=status,
        )

        try:
            params = {}
            if customer_id:
                params["customer_id"] = customer_id
            if date:
                params["date"] = date
            if status:
                params["status"] = status

            response = self._session.get(
                f"{self.base_url}appointments",
                params=params,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return [self._parse_appointment(a) for a in response.json()]
            else:
                raise AppointmentError(
                    f"Failed to list appointments: {response.status_code}",
                    error_code="APPOINTMENT_LIST_FAILED",
                )
        except requests.RequestException as e:
            logger.error("appointment_list_error", error=str(e))
            raise AppointmentError(
                f"Failed to list appointments: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def cancel_appointment(
        self, appointment_id: str, reason: str = "Cancelled by caller"
    ) -> Appointment:
        """Cancel an existing appointment.

        Args:
            appointment_id: Appointment ID
            reason: Cancellation reason

        Returns:
            Updated Appointment object

        Raises:
            AppointmentError: If the API request fails
        """
        self._check_configured()

        logger.info("cancelling_appointment", appointment_id=appointment_id)

        try:
            response = self._session.post(
                f"{self.base_url}appointments/{appointment_id}/cancel",
                json={"reason": reason},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return self._parse_appointment(response.json())
            elif response.status_code == 404:
                raise AppointmentError(
                    "Appointment not found",
                    error_code="APPOINTMENT_NOT_FOUND",
                )
            else:
                data = self._safe_json(response)
                raise AppointmentError(
                    data.get(
                        "error", f"Failed to cancel appointment: {response.status_code}"
                    ),
                    error_code="APPOINTMENT_CANCEL_FAILED",
                )
        except requests.RequestException as e:
            logger.error(
                "appointment_cancel_error", error=str(e), appointment_id=appointment_id
            )
            raise AppointmentError(
                f"Failed to cancel appointment: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def reschedule_appointment(
        self, appointment_id: str, new_date: str, new_time: str
    ) -> Appointment:
        """Reschedule an existing appointment to a new date/time.

        Args:
            appointment_id: Appointment ID
            new_date: New date in YYYY-MM-DD format
            new_time: New start time in HH:MM format

        Returns:
            Updated Appointment object

        Raises:
            AppointmentError: If the API request fails or conflict exists
        """
        self._check_configured()

        logger.info(
            "rescheduling_appointment",
            appointment_id=appointment_id,
            new_date=new_date,
            new_time=new_time,
        )

        try:
            response = self._session.post(
                f"{self.base_url}appointments/{appointment_id}/reschedule",
                json={"new_date": new_date, "new_time": new_time},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return self._parse_appointment(response.json())
            elif response.status_code == 404:
                raise AppointmentError(
                    "Appointment not found",
                    error_code="APPOINTMENT_NOT_FOUND",
                )
            elif response.status_code == 409:
                data = self._safe_json(response)
                raise AppointmentError(
                    data.get("error", "Time slot conflict on the new date"),
                    error_code="APPOINTMENT_CONFLICT",
                )
            else:
                data = self._safe_json(response)
                raise AppointmentError(
                    data.get("error", f"Failed to reschedule: {response.status_code}"),
                    error_code="APPOINTMENT_RESCHEDULE_FAILED",
                )
        except requests.RequestException as e:
            logger.error(
                "appointment_reschedule_error",
                error=str(e),
                appointment_id=appointment_id,
            )
            raise AppointmentError(
                f"Failed to reschedule appointment: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def get_service_types(self) -> Dict[str, Any]:
        """Get available service types and their durations.

        Returns:
            Dict mapping service_type keys to info dicts

        Raises:
            AppointmentError: If the API request fails
        """
        self._check_configured()

        try:
            response = self._session.get(
                f"{self.base_url}service-types",
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return response.json()
            else:
                raise AppointmentError(
                    f"Failed to get service types: {response.status_code}",
                    error_code="SERVICE_TYPES_FAILED",
                )
        except requests.RequestException as e:
            logger.error("appointment_service_types_error", error=str(e))
            raise AppointmentError(
                f"Failed to get service types: {str(e)}",
                error_code="APPOINTMENT_NETWORK_ERROR",
            )

    def _check_configured(self) -> None:
        """Raise AppointmentError if client is not configured."""
        if not self.is_configured():
            raise AppointmentError(
                "Appointment API URL not configured",
                error_code="APPOINTMENT_NOT_CONFIGURED",
            )

    def _safe_json(self, response: requests.Response) -> Dict[str, Any]:
        """Safely parse JSON from a response."""
        try:
            return response.json()
        except Exception:
            return {"error": response.text}

    def _parse_appointment(self, data: Dict[str, Any]) -> Appointment:
        """Parse appointment data from API response."""
        return Appointment(
            appointment_id=data["appointment_id"],
            customer_id=data["customer_id"],
            appointment_date=data["appointment_date"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            service_type=data["service_type"],
            service_label=data.get("service_label", ""),
            duration_minutes=int(data.get("duration_minutes", 0)),
            status=data.get("status", "confirmed"),
            notes=data.get("notes", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            cancellation_reason=data.get("cancellation_reason"),
            cancelled_at=data.get("cancelled_at"),
            previous_date=data.get("previous_date"),
            previous_time=data.get("previous_time"),
        )
