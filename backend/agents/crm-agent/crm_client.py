"""Synchronous CRM HTTP client for the CRM capability agent.

Ported from the voice agent's SimpleCRMService (which uses aiohttp) to use
synchronous `requests` because Strands @tool functions are synchronous.

This client communicates with the Simple CRM REST API (API Gateway + Lambda)
deployed by the CrmStack.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
import structlog

logger = structlog.get_logger(__name__)


class CRMError(Exception):
    """Exception raised for CRM API errors."""

    def __init__(self, message: str, error_code: str = "CRM_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


@dataclass
class Customer:
    """Customer data from CRM."""

    customer_id: str
    phone: str
    email: Optional[str]
    first_name: str
    last_name: str
    account_type: str
    account_status: str
    account_last4: Optional[str] = None
    recent_transaction: Optional[Dict[str, Any]] = None
    address: Optional[Dict[str, str]] = None
    member_since: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "phone": self.phone,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "account_type": self.account_type,
            "account_status": self.account_status,
            "account_last4": self.account_last4,
            "recent_transaction": self.recent_transaction,
            "address": self.address,
            "member_since": self.member_since,
        }


@dataclass
class Case:
    """Support case from CRM."""

    case_id: str
    customer_id: str
    subject: str
    description: str
    status: str
    priority: str
    category: str
    created_at: str
    updated_at: str
    notes: List[Dict[str, str]] = field(default_factory=list)
    assigned_to: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "customer_id": self.customer_id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "notes": self.notes,
            "assigned_to": self.assigned_to,
        }


class CRMClient:
    """Synchronous HTTP client for the Simple CRM API.

    This is the sync equivalent of SimpleCRMService (which uses aiohttp).
    Used by the CRM capability agent because Strands @tool functions are synchronous.

    Uses a persistent requests.Session to reuse TCP connections across calls,
    reducing connection setup overhead (~50-100ms per call).

    Example:
        >>> client = CRMClient()
        >>> customer = client.search_customer_by_phone("555-0100")
        >>> if customer:
        ...     cases = client.get_customer_cases(customer.customer_id, status="open")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ):
        """Initialize the CRM client.

        Args:
            base_url: CRM API base URL (defaults to CRM_API_URL env var)
            timeout_seconds: Request timeout in seconds
        """
        self.base_url = base_url or os.environ.get("CRM_API_URL", "")
        self.timeout = timeout_seconds
        # Persistent session reuses TCP connections (keep-alive)
        self._session = requests.Session()

        if not self.base_url:
            logger.warning("crm_api_url_not_configured")

    def is_configured(self) -> bool:
        """Check if the client is properly configured."""
        return bool(self.base_url)

    def search_customer_by_phone(self, phone: str) -> Optional[Customer]:
        """Search for a customer by phone number.

        Args:
            phone: Phone number to search for

        Returns:
            Customer object if found, None otherwise

        Raises:
            CRMError: If the API request fails
        """
        self._check_configured()

        logger.info("searching_customer_by_phone", phone=phone)

        try:
            response = self._session.get(
                f"{self.base_url}customers",
                params={"phone": phone},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return self._parse_customer(data[0])
                return None
            elif response.status_code == 404:
                return None
            else:
                raise CRMError(
                    f"Failed to search customer: {response.status_code} - {response.text}",
                    error_code="CRM_SEARCH_FAILED",
                )
        except requests.RequestException as e:
            logger.error("crm_search_error", error=str(e), phone=phone)
            raise CRMError(
                f"Failed to search customer: {str(e)}",
                error_code="CRM_NETWORK_ERROR",
            )

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        """Get a customer by ID.

        Args:
            customer_id: Customer ID

        Returns:
            Customer object if found, None otherwise

        Raises:
            CRMError: If the API request fails
        """
        self._check_configured()

        logger.info("getting_customer", customer_id=customer_id)

        try:
            response = self._session.get(
                f"{self.base_url}customers/{customer_id}",
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return self._parse_customer(response.json())
            elif response.status_code == 404:
                return None
            else:
                raise CRMError(
                    f"Failed to get customer: {response.status_code} - {response.text}",
                    error_code="CRM_GET_FAILED",
                )
        except requests.RequestException as e:
            logger.error("crm_get_error", error=str(e), customer_id=customer_id)
            raise CRMError(
                f"Failed to get customer: {str(e)}",
                error_code="CRM_NETWORK_ERROR",
            )

    def get_customer_cases(
        self, customer_id: str, status: Optional[str] = None
    ) -> List[Case]:
        """Get all cases for a customer.

        Args:
            customer_id: Customer ID
            status: Optional status filter (open, in_progress, etc.)

        Returns:
            List of Case objects

        Raises:
            CRMError: If the API request fails
        """
        self._check_configured()

        logger.info("getting_customer_cases", customer_id=customer_id, status=status)

        try:
            params = {}
            if status:
                params["status"] = status

            response = self._session.get(
                f"{self.base_url}customers/{customer_id}/cases",
                params=params,
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return [self._parse_case(c) for c in response.json()]
            else:
                raise CRMError(
                    f"Failed to get cases: {response.status_code} - {response.text}",
                    error_code="CRM_GET_CASES_FAILED",
                )
        except requests.RequestException as e:
            logger.error("crm_get_cases_error", error=str(e), customer_id=customer_id)
            raise CRMError(
                f"Failed to get cases: {str(e)}",
                error_code="CRM_NETWORK_ERROR",
            )

    def create_case(
        self,
        customer_id: str,
        subject: str,
        description: str,
        category: str = "general",
        priority: str = "medium",
    ) -> Case:
        """Create a new support case.

        Args:
            customer_id: Customer ID
            subject: Case subject
            description: Case description
            category: Case category (billing, technical, account, order, general)
            priority: Priority level (low, medium, high, urgent)

        Returns:
            Created Case object

        Raises:
            CRMError: If the API request fails
        """
        self._check_configured()

        logger.info(
            "creating_case",
            customer_id=customer_id,
            subject=subject,
            category=category,
            priority=priority,
        )

        try:
            payload = {
                "customer_id": customer_id,
                "subject": subject,
                "description": description,
                "category": category,
                "priority": priority,
            }

            response = self._session.post(
                f"{self.base_url}cases",
                json=payload,
                timeout=self.timeout,
            )

            if response.status_code == 201:
                return self._parse_case(response.json())
            else:
                raise CRMError(
                    f"Failed to create case: {response.status_code} - {response.text}",
                    error_code="CRM_CREATE_CASE_FAILED",
                )
        except requests.RequestException as e:
            logger.error("crm_create_case_error", error=str(e), customer_id=customer_id)
            raise CRMError(
                f"Failed to create case: {str(e)}",
                error_code="CRM_NETWORK_ERROR",
            )

    def add_case_note(
        self, case_id: str, content: str, author: str = "voice-agent"
    ) -> Case:
        """Add a note to an existing case.

        Args:
            case_id: Case ID
            content: Note content
            author: Note author (defaults to "voice-agent")

        Returns:
            Updated Case object

        Raises:
            CRMError: If the API request fails
        """
        self._check_configured()

        logger.info("adding_case_note", case_id=case_id)

        try:
            response = self._session.post(
                f"{self.base_url}cases/{case_id}/notes",
                json={"content": content, "author": author},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                return self._parse_case(response.json())
            else:
                raise CRMError(
                    f"Failed to add case note: {response.status_code} - {response.text}",
                    error_code="CRM_ADD_NOTE_FAILED",
                )
        except requests.RequestException as e:
            logger.error("crm_add_note_error", error=str(e), case_id=case_id)
            raise CRMError(
                f"Failed to add case note: {str(e)}",
                error_code="CRM_NETWORK_ERROR",
            )

    def verify_account_number(self, customer: Customer, provided_last4: str) -> bool:
        """Verify customer's account number (KBA).

        Args:
            customer: Customer object (must have account_last4)
            provided_last4: Last 4 digits provided by customer

        Returns:
            True if verified, False otherwise
        """
        if not customer.account_last4:
            return False
        return customer.account_last4 == provided_last4

    def verify_recent_transaction(
        self, customer: Customer, date: str, amount: float, merchant: str
    ) -> bool:
        """Verify customer's recent transaction (KBA).

        Args:
            customer: Customer object (must have recent_transaction)
            date: Transaction date (YYYY-MM-DD)
            amount: Transaction amount
            merchant: Merchant name

        Returns:
            True if verified, False otherwise
        """
        if not customer.recent_transaction:
            return False

        tx = customer.recent_transaction
        return (
            tx.get("date") == date
            and abs(tx.get("amount", 0) - amount) < 0.01
            and tx.get("merchant", "").lower() == merchant.lower()
        )

    def _check_configured(self) -> None:
        """Raise CRMError if client is not configured."""
        if not self.is_configured():
            raise CRMError(
                "CRM API URL not configured",
                error_code="CRM_NOT_CONFIGURED",
            )

    def _parse_customer(self, data: Dict[str, Any]) -> Customer:
        """Parse customer data from API response."""
        return Customer(
            customer_id=data["customer_id"],
            phone=data["phone"],
            email=data.get("email"),
            first_name=data["first_name"],
            last_name=data["last_name"],
            account_type=data.get("account_type", "basic"),
            account_status=data.get("account_status", "active"),
            account_last4=data.get("account_last4"),
            recent_transaction=data.get("recent_transaction"),
            address=data.get("address"),
            member_since=data.get("member_since"),
        )

    def _parse_case(self, data: Dict[str, Any]) -> Case:
        """Parse case data from API response."""
        return Case(
            case_id=data["case_id"],
            customer_id=data["customer_id"],
            subject=data["subject"],
            description=data.get("description", ""),
            status=data.get("status", "open"),
            priority=data.get("priority", "medium"),
            category=data.get("category", "general"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            notes=data.get("notes", []),
            assigned_to=data.get("assigned_to"),
        )
