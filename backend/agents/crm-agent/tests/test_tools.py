"""Tests for CRM agent tools (main.py @tool functions).

Each tool is tested in isolation by mocking the CRM client. The tools are
plain functions decorated with @tool — we call them directly.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# The agent's main.py uses `from crm_client import ...` (no package prefix).
# To make that import work in tests, we add the agent source directory to the path.
# This mirrors the Dockerfile layout where crm_client.py sits beside main.py.
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from crm_client import CRMClient, CRMError, Customer, Case  # noqa: E402

# We need to import the tool functions. main.py reads env vars and sets up
# module-level globals. We patch them before importing.
with patch.dict(
    "os.environ",
    {
        "CRM_API_URL": "http://fake-crm/",
        "AWS_REGION": "us-east-1",
    },
):
    from main import (  # noqa: E402
        lookup_customer,
        create_support_case,
        add_case_note,
        verify_account_number,
        verify_recent_transaction,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CUSTOMER = Customer(
    customer_id="CUST-001",
    phone="555-0100",
    email="alice@example.com",
    first_name="Alice",
    last_name="Smith",
    account_type="premium",
    account_status="active",
    account_last4="1234",
    recent_transaction={
        "date": "2026-01-28",
        "amount": 89.99,
        "merchant": "TechStore Online",
    },
)

SAMPLE_CASE = Case(
    case_id="TICKET-2026-00001",
    customer_id="CUST-001",
    subject="Billing dispute",
    description="Charged twice",
    status="open",
    priority="high",
    category="billing",
    created_at="2026-02-01T10:00:00Z",
    updated_at="2026-02-01T10:00:00Z",
    notes=[{"content": "Initial report", "author": "voice-agent"}],
)


@pytest.fixture(autouse=True)
def mock_crm_client():
    """Replace the global CRM client with a mock for every test."""
    mock = MagicMock(spec=CRMClient)
    mock.is_configured.return_value = True
    with (
        patch("main._crm_client", mock),
        patch("main._get_crm_client", return_value=mock),
    ):
        yield mock


# ---------------------------------------------------------------------------
# lookup_customer
# ---------------------------------------------------------------------------


class TestLookupCustomer:
    def test_found_with_open_cases(self, mock_crm_client):
        mock_crm_client.search_customer_by_phone.return_value = SAMPLE_CUSTOMER
        mock_crm_client.get_customer_cases.return_value = [SAMPLE_CASE]

        result = lookup_customer(phone="555-0100")

        assert result["found"] is True
        assert result["customer"]["customer_id"] == "CUST-001"
        assert result["open_case_count"] == 1
        assert "Billing dispute" in result["message"]

    def test_found_no_cases(self, mock_crm_client):
        mock_crm_client.search_customer_by_phone.return_value = SAMPLE_CUSTOMER
        mock_crm_client.get_customer_cases.return_value = []

        result = lookup_customer(phone="555-0100")

        assert result["found"] is True
        assert result["open_case_count"] == 0
        assert "No open cases" in result["message"]

    def test_not_found(self, mock_crm_client):
        mock_crm_client.search_customer_by_phone.return_value = None

        result = lookup_customer(phone="555-9999")

        assert result["found"] is False
        assert "No customer found" in result["message"]

    def test_empty_phone(self):
        result = lookup_customer(phone="")
        assert result["found"] is False
        assert "required" in result["error"].lower()

    def test_whitespace_phone(self):
        result = lookup_customer(phone="   ")
        assert result["found"] is False

    def test_crm_not_configured(self, mock_crm_client):
        mock_crm_client.is_configured.return_value = False

        result = lookup_customer(phone="555-0100")

        assert result["found"] is False
        assert "not configured" in result["error"].lower()

    def test_crm_error(self, mock_crm_client):
        mock_crm_client.search_customer_by_phone.side_effect = CRMError("timeout")

        result = lookup_customer(phone="555-0100")

        assert result["found"] is False
        assert "CRM error" in result["error"]


# ---------------------------------------------------------------------------
# create_support_case
# ---------------------------------------------------------------------------


class TestCreateSupportCase:
    def test_success(self, mock_crm_client):
        mock_crm_client.create_case.return_value = SAMPLE_CASE

        result = create_support_case(
            customer_id="CUST-001",
            subject="Billing dispute",
            description="Charged twice",
            category="billing",
            priority="high",
        )

        assert result["created"] is True
        assert result["case"]["case_id"] == "TICKET-2026-00001"

    def test_missing_customer_id(self):
        result = create_support_case(customer_id="", subject="Sub", description="Desc")
        assert result["created"] is False
        assert "required" in result["error"].lower()

    def test_missing_subject(self):
        result = create_support_case(
            customer_id="CUST-001", subject="", description="Desc"
        )
        assert result["created"] is False

    def test_missing_description(self):
        result = create_support_case(
            customer_id="CUST-001", subject="Sub", description=""
        )
        assert result["created"] is False

    def test_invalid_category(self):
        result = create_support_case(
            customer_id="CUST-001",
            subject="Sub",
            description="Desc",
            category="invalid",
        )
        assert result["created"] is False
        assert "Invalid category" in result["error"]

    def test_invalid_priority(self):
        result = create_support_case(
            customer_id="CUST-001",
            subject="Sub",
            description="Desc",
            priority="critical",
        )
        assert result["created"] is False
        assert "Invalid priority" in result["error"]

    def test_crm_error(self, mock_crm_client):
        mock_crm_client.create_case.side_effect = CRMError("fail")

        result = create_support_case(
            customer_id="CUST-001", subject="Sub", description="Desc"
        )
        assert result["created"] is False


# ---------------------------------------------------------------------------
# add_case_note
# ---------------------------------------------------------------------------


class TestAddCaseNote:
    def test_success(self, mock_crm_client):
        updated_case = Case(
            **{
                **SAMPLE_CASE.__dict__,
                "notes": [
                    {"content": "Initial report", "author": "voice-agent"},
                    {"content": "Follow-up", "author": "voice-agent"},
                ],
            }
        )
        mock_crm_client.add_case_note.return_value = updated_case

        result = add_case_note(case_id="TICKET-2026-00001", content="Follow-up")

        assert result["added"] is True
        assert "2 note(s)" in result["message"]

    def test_empty_case_id(self):
        result = add_case_note(case_id="", content="Note")
        assert result["added"] is False
        assert "required" in result["error"].lower()

    def test_empty_content(self):
        result = add_case_note(case_id="T-1", content="")
        assert result["added"] is False


# ---------------------------------------------------------------------------
# verify_account_number
# ---------------------------------------------------------------------------


class TestVerifyAccountNumber:
    def test_verified(self, mock_crm_client):
        mock_crm_client.get_customer.return_value = SAMPLE_CUSTOMER
        mock_crm_client.verify_account_number.return_value = True

        result = verify_account_number(customer_id="CUST-001", last4="1234")

        assert result["verified"] is True

    def test_not_verified(self, mock_crm_client):
        mock_crm_client.get_customer.return_value = SAMPLE_CUSTOMER
        mock_crm_client.verify_account_number.return_value = False

        result = verify_account_number(customer_id="CUST-001", last4="0000")

        assert result["verified"] is False
        assert "does not match" in result["message"]

    def test_customer_not_found(self, mock_crm_client):
        mock_crm_client.get_customer.return_value = None

        result = verify_account_number(customer_id="CUST-999", last4="1234")

        assert result["verified"] is False
        assert "not found" in result["error"].lower()

    def test_no_account_last4(self, mock_crm_client):
        customer_no_last4 = Customer(
            customer_id="CUST-002",
            phone="555-0200",
            email=None,
            first_name="Bob",
            last_name="Jones",
            account_type="basic",
            account_status="active",
            account_last4=None,
        )
        mock_crm_client.get_customer.return_value = customer_no_last4

        result = verify_account_number(customer_id="CUST-002", last4="1234")

        assert result["verified"] is False
        assert "not available" in result["message"].lower()

    def test_invalid_last4_length(self):
        result = verify_account_number(customer_id="CUST-001", last4="12")
        assert result["verified"] is False
        assert "4 digits" in result["error"]

    def test_non_digit_last4(self):
        result = verify_account_number(customer_id="CUST-001", last4="abcd")
        assert result["verified"] is False

    def test_empty_customer_id(self):
        result = verify_account_number(customer_id="", last4="1234")
        assert result["verified"] is False


# ---------------------------------------------------------------------------
# verify_recent_transaction
# ---------------------------------------------------------------------------


class TestVerifyRecentTransaction:
    def test_verified(self, mock_crm_client):
        mock_crm_client.get_customer.return_value = SAMPLE_CUSTOMER
        mock_crm_client.verify_recent_transaction.return_value = True

        result = verify_recent_transaction(
            customer_id="CUST-001",
            date="2026-01-28",
            amount=89.99,
            merchant="TechStore Online",
        )

        assert result["verified"] is True

    def test_not_verified(self, mock_crm_client):
        mock_crm_client.get_customer.return_value = SAMPLE_CUSTOMER
        mock_crm_client.verify_recent_transaction.return_value = False

        result = verify_recent_transaction(
            customer_id="CUST-001",
            date="2026-01-28",
            amount=100.00,
            merchant="TechStore Online",
        )

        assert result["verified"] is False

    def test_no_recent_transaction(self, mock_crm_client):
        customer = Customer(
            customer_id="CUST-002",
            phone="555-0200",
            email=None,
            first_name="Bob",
            last_name="Jones",
            account_type="basic",
            account_status="active",
            recent_transaction=None,
        )
        mock_crm_client.get_customer.return_value = customer

        result = verify_recent_transaction(
            customer_id="CUST-002",
            date="2026-01-28",
            amount=89.99,
            merchant="TechStore",
        )

        assert result["verified"] is False
        assert "not available" in result["message"].lower()

    def test_empty_customer_id(self):
        result = verify_recent_transaction(
            customer_id="", date="2026-01-28", amount=89.99, merchant="Store"
        )
        assert result["verified"] is False

    def test_empty_date(self):
        result = verify_recent_transaction(
            customer_id="CUST-001", date="", amount=89.99, merchant="Store"
        )
        assert result["verified"] is False

    def test_empty_merchant(self):
        result = verify_recent_transaction(
            customer_id="CUST-001", date="2026-01-28", amount=89.99, merchant=""
        )
        assert result["verified"] is False
