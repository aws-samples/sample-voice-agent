"""Tests for the CRM client (crm_client.py).

Covers CRMClient HTTP interactions, parsing, verification logic,
and error handling — all with mocked HTTP responses.
"""

import pytest
import requests

from crm_client import Case, CRMClient, CRMError, Customer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CUSTOMER_DATA = {
    "customer_id": "CUST-001",
    "phone": "555-0100",
    "email": "alice@example.com",
    "first_name": "Alice",
    "last_name": "Smith",
    "account_type": "premium",
    "account_status": "active",
    "account_last4": "1234",
    "recent_transaction": {
        "date": "2026-01-28",
        "amount": 89.99,
        "merchant": "TechStore Online",
    },
    "address": {"city": "Seattle", "state": "WA"},
    "member_since": "2024-03-15",
}

SAMPLE_CASE_DATA = {
    "case_id": "TICKET-2026-00001",
    "customer_id": "CUST-001",
    "subject": "Billing dispute",
    "description": "Charged twice in October",
    "status": "open",
    "priority": "high",
    "category": "billing",
    "created_at": "2026-02-01T10:00:00Z",
    "updated_at": "2026-02-01T10:00:00Z",
    "notes": [{"content": "Initial report", "author": "voice-agent"}],
    "assigned_to": "agent-7",
}


@pytest.fixture
def client():
    """Return a CRMClient pointed at a fake URL."""
    return CRMClient(base_url="http://fake-crm/", timeout_seconds=1.0)


@pytest.fixture
def unconfigured_client():
    """Return a CRMClient with no base_url."""
    return CRMClient(base_url="")


# ---------------------------------------------------------------------------
# Customer dataclass
# ---------------------------------------------------------------------------


class TestCustomer:
    def test_full_name(self):
        c = Customer(
            customer_id="1",
            phone="555",
            email=None,
            first_name="Alice",
            last_name="Smith",
            account_type="basic",
            account_status="active",
        )
        assert c.full_name == "Alice Smith"

    def test_to_dict_includes_all_fields(self):
        c = Customer(
            customer_id="1",
            phone="555",
            email="a@b.com",
            first_name="Alice",
            last_name="Smith",
            account_type="premium",
            account_status="active",
            account_last4="9999",
        )
        d = c.to_dict()
        assert d["customer_id"] == "1"
        assert d["full_name"] == "Alice Smith"
        assert d["account_last4"] == "9999"


# ---------------------------------------------------------------------------
# Case dataclass
# ---------------------------------------------------------------------------


class TestCase:
    def test_to_dict(self):
        c = Case(
            case_id="T-1",
            customer_id="C-1",
            subject="Test",
            description="Desc",
            status="open",
            priority="low",
            category="general",
            created_at="2026-01-01",
            updated_at="2026-01-02",
            notes=[],
        )
        d = c.to_dict()
        assert d["case_id"] == "T-1"
        assert d["notes"] == []

    def test_notes_default_factory(self):
        c = Case(
            case_id="T-1",
            customer_id="C-1",
            subject="Test",
            description="Desc",
            status="open",
            priority="low",
            category="general",
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        assert c.notes == []


# ---------------------------------------------------------------------------
# CRMClient — configuration
# ---------------------------------------------------------------------------


class TestCRMClientConfig:
    def test_is_configured(self, client):
        assert client.is_configured() is True

    def test_is_not_configured(self, unconfigured_client):
        assert unconfigured_client.is_configured() is False

    def test_check_configured_raises(self, unconfigured_client):
        with pytest.raises(CRMError) as exc_info:
            unconfigured_client._check_configured()
        assert exc_info.value.error_code == "CRM_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# CRMClient — search_customer_by_phone
# ---------------------------------------------------------------------------


class TestSearchCustomerByPhone:
    def test_found(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers",
            json=[SAMPLE_CUSTOMER_DATA],
            status_code=200,
        )
        result = client.search_customer_by_phone("555-0100")
        assert result is not None
        assert result.customer_id == "CUST-001"
        assert result.full_name == "Alice Smith"

    def test_empty_list_returns_none(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers",
            json=[],
            status_code=200,
        )
        assert client.search_customer_by_phone("555-9999") is None

    def test_404_returns_none(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers",
            status_code=404,
        )
        assert client.search_customer_by_phone("555-9999") is None

    def test_server_error_raises(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers",
            status_code=500,
            text="Internal Server Error",
        )
        with pytest.raises(CRMError) as exc_info:
            client.search_customer_by_phone("555-0100")
        assert exc_info.value.error_code == "CRM_SEARCH_FAILED"

    def test_network_error_raises(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers",
            exc=requests.ConnectionError("Connection refused"),
        )
        with pytest.raises(CRMError) as exc_info:
            client.search_customer_by_phone("555-0100")
        assert exc_info.value.error_code == "CRM_NETWORK_ERROR"

    def test_not_configured_raises(self, unconfigured_client):
        with pytest.raises(CRMError) as exc_info:
            unconfigured_client.search_customer_by_phone("555-0100")
        assert exc_info.value.error_code == "CRM_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# CRMClient — get_customer
# ---------------------------------------------------------------------------


class TestGetCustomer:
    def test_found(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers/CUST-001",
            json=SAMPLE_CUSTOMER_DATA,
            status_code=200,
        )
        result = client.get_customer("CUST-001")
        assert result is not None
        assert result.email == "alice@example.com"

    def test_not_found(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers/CUST-999",
            status_code=404,
        )
        assert client.get_customer("CUST-999") is None

    def test_server_error(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers/CUST-001",
            status_code=502,
            text="Bad Gateway",
        )
        with pytest.raises(CRMError) as exc_info:
            client.get_customer("CUST-001")
        assert exc_info.value.error_code == "CRM_GET_FAILED"


# ---------------------------------------------------------------------------
# CRMClient — get_customer_cases
# ---------------------------------------------------------------------------


class TestGetCustomerCases:
    def test_returns_cases(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers/CUST-001/cases",
            json=[SAMPLE_CASE_DATA],
            status_code=200,
        )
        cases = client.get_customer_cases("CUST-001")
        assert len(cases) == 1
        assert cases[0].case_id == "TICKET-2026-00001"

    def test_status_filter_passed_as_param(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers/CUST-001/cases",
            json=[],
            status_code=200,
        )
        client.get_customer_cases("CUST-001", status="open")
        assert requests_mock.last_request.qs == {"status": ["open"]}

    def test_server_error(self, client, requests_mock):
        requests_mock.get(
            "http://fake-crm/customers/CUST-001/cases",
            status_code=500,
            text="fail",
        )
        with pytest.raises(CRMError) as exc_info:
            client.get_customer_cases("CUST-001")
        assert exc_info.value.error_code == "CRM_GET_CASES_FAILED"


# ---------------------------------------------------------------------------
# CRMClient — create_case
# ---------------------------------------------------------------------------


class TestCreateCase:
    def test_success(self, client, requests_mock):
        requests_mock.post(
            "http://fake-crm/cases",
            json=SAMPLE_CASE_DATA,
            status_code=201,
        )
        case = client.create_case(
            customer_id="CUST-001",
            subject="Billing dispute",
            description="Charged twice",
            category="billing",
            priority="high",
        )
        assert case.case_id == "TICKET-2026-00001"

    def test_server_error(self, client, requests_mock):
        requests_mock.post(
            "http://fake-crm/cases",
            status_code=400,
            text="Bad Request",
        )
        with pytest.raises(CRMError) as exc_info:
            client.create_case("CUST-001", "Sub", "Desc")
        assert exc_info.value.error_code == "CRM_CREATE_CASE_FAILED"


# ---------------------------------------------------------------------------
# CRMClient — add_case_note
# ---------------------------------------------------------------------------


class TestAddCaseNote:
    def test_success(self, client, requests_mock):
        updated = {
            **SAMPLE_CASE_DATA,
            "notes": [{"content": "note1", "author": "voice-agent"}],
        }
        requests_mock.post(
            "http://fake-crm/cases/TICKET-2026-00001/notes",
            json=updated,
            status_code=200,
        )
        case = client.add_case_note("TICKET-2026-00001", "note1")
        assert len(case.notes) == 1

    def test_server_error(self, client, requests_mock):
        requests_mock.post(
            "http://fake-crm/cases/TICKET-2026-00001/notes",
            status_code=500,
            text="fail",
        )
        with pytest.raises(CRMError) as exc_info:
            client.add_case_note("TICKET-2026-00001", "note")
        assert exc_info.value.error_code == "CRM_ADD_NOTE_FAILED"


# ---------------------------------------------------------------------------
# CRMClient — verification methods
# ---------------------------------------------------------------------------


class TestVerification:
    def _make_customer(self, **overrides):
        defaults = {
            "customer_id": "CUST-001",
            "phone": "555-0100",
            "email": None,
            "first_name": "Alice",
            "last_name": "Smith",
            "account_type": "basic",
            "account_status": "active",
        }
        defaults.update(overrides)
        return Customer(**defaults)

    def test_verify_account_number_match(self, client):
        customer = self._make_customer(account_last4="1234")
        assert client.verify_account_number(customer, "1234") is True

    def test_verify_account_number_mismatch(self, client):
        customer = self._make_customer(account_last4="1234")
        assert client.verify_account_number(customer, "5678") is False

    def test_verify_account_number_none(self, client):
        customer = self._make_customer(account_last4=None)
        assert client.verify_account_number(customer, "1234") is False

    def test_verify_transaction_match(self, client):
        customer = self._make_customer(
            recent_transaction={
                "date": "2026-01-28",
                "amount": 89.99,
                "merchant": "TechStore Online",
            }
        )
        assert (
            client.verify_recent_transaction(
                customer, "2026-01-28", 89.99, "TechStore Online"
            )
            is True
        )

    def test_verify_transaction_case_insensitive(self, client):
        customer = self._make_customer(
            recent_transaction={
                "date": "2026-01-28",
                "amount": 89.99,
                "merchant": "TechStore Online",
            }
        )
        assert (
            client.verify_recent_transaction(
                customer, "2026-01-28", 89.99, "techstore online"
            )
            is True
        )

    def test_verify_transaction_mismatch(self, client):
        customer = self._make_customer(
            recent_transaction={
                "date": "2026-01-28",
                "amount": 89.99,
                "merchant": "TechStore Online",
            }
        )
        assert (
            client.verify_recent_transaction(
                customer, "2026-01-28", 100.00, "TechStore Online"
            )
            is False
        )

    def test_verify_transaction_none(self, client):
        customer = self._make_customer(recent_transaction=None)
        assert (
            client.verify_recent_transaction(customer, "2026-01-28", 89.99, "TechStore")
            is False
        )
