"""Unit tests for CRM API Lambda handler.

Tests cover all API endpoints including:
- Customer CRUD operations
- Case management
- Interaction logging
- Admin endpoints (seed/reset)
- Error handling
"""

import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock boto3 before importing index
sys.modules["boto3"] = Mock()
sys.modules["boto3.dynamodb"] = Mock()
sys.modules["boto3.dynamodb.conditions"] = Mock()

from index import (
    handler,
    create_response,
    generate_customer_id,
    generate_case_id,
    validate_customer_data,
    validate_case_data,
    DecimalEncoder,
)


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_create_response_structure(self):
        """Test create_response returns proper API Gateway format."""
        response = create_response(200, {"test": "data"})

        assert response["statusCode"] == 200
        assert "headers" in response
        assert response["headers"]["Content-Type"] == "application/json"
        assert "Access-Control-Allow-Origin" in response["headers"]
        assert json.loads(response["body"]) == {"test": "data"}

    def test_create_response_with_decimal(self):
        """Test create_response handles Decimal types."""
        response = create_response(200, {"amount": Decimal("99.99")})
        body = json.loads(response["body"])

        assert body["amount"] == 99.99

    def test_generate_customer_id_format(self):
        """Test customer ID generation format."""
        customer_id = generate_customer_id()

        assert customer_id.startswith("cust-")
        assert len(customer_id) == 17  # cust- + 12 hex chars

    def test_generate_case_id_format(self):
        """Test case ID generation format."""
        case_id = generate_case_id()
        year = datetime.now().year

        assert case_id.startswith(f"TICKET-{year}-")
        assert len(case_id) == 18  # TICKET-YYYY-XXXXX

    def test_validate_customer_data_valid(self):
        """Test validation with valid customer data."""
        data = {
            "phone": "555-0100",
            "first_name": "John",
            "last_name": "Smith",
        }

        is_valid, error = validate_customer_data(data)

        assert is_valid is True
        assert error is None

    def test_validate_customer_data_missing_phone(self):
        """Test validation with missing phone."""
        data = {
            "first_name": "John",
            "last_name": "Smith",
        }

        is_valid, error = validate_customer_data(data)

        assert is_valid is False
        assert "phone" in error.lower()

    def test_validate_customer_data_invalid_phone(self):
        """Test validation with invalid phone format."""
        data = {
            "phone": "abc-def-ghij",
            "first_name": "John",
            "last_name": "Smith",
        }

        is_valid, error = validate_customer_data(data)

        assert is_valid is False
        assert "phone" in error.lower()

    def test_validate_case_data_valid(self):
        """Test validation with valid case data."""
        data = {
            "customer_id": "cust-001",
            "subject": "Test case",
        }

        is_valid, error = validate_case_data(data)

        assert is_valid is True
        assert error is None

    def test_validate_case_data_missing_customer_id(self):
        """Test validation with missing customer_id."""
        data = {
            "subject": "Test case",
        }

        is_valid, error = validate_case_data(data)

        assert is_valid is False
        assert "customer_id" in error.lower()


class TestCustomerEndpoints:
    """Tests for customer API endpoints."""

    @pytest.fixture
    def mock_customers_table(self):
        """Create mock customers table."""
        with patch("index.customers_table") as mock_table:
            yield mock_table

    def test_get_customers_by_phone_success(self, mock_customers_table):
        """Test GET /customers?phone=555-0100 returns customer."""
        mock_customers_table.query.return_value = {
            "Items": [
                {
                    "customer_id": "cust-001",
                    "phone": "555-0100",
                    "first_name": "John",
                    "last_name": "Smith",
                }
            ]
        }

        event = {
            "httpMethod": "GET",
            "path": "/customers",
            "queryStringParameters": {"phone": "555-0100"},
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body) == 1
        assert body[0]["phone"] == "555-0100"

    def test_get_customers_by_email_success(self, mock_customers_table):
        """Test GET /customers?email=john@example.com returns customer."""
        mock_customers_table.query.return_value = {
            "Items": [
                {
                    "customer_id": "cust-001",
                    "email": "john@example.com",
                    "first_name": "John",
                }
            ]
        }

        event = {
            "httpMethod": "GET",
            "path": "/customers",
            "queryStringParameters": {"email": "john@example.com"},
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body[0]["email"] == "john@example.com"

    def test_create_customer_success(self, mock_customers_table):
        """Test POST /customers creates customer."""
        event = {
            "httpMethod": "POST",
            "path": "/customers",
            "body": json.dumps(
                {
                    "phone": "555-0100",
                    "first_name": "John",
                    "last_name": "Smith",
                    "email": "john@example.com",
                }
            ),
        }

        response = handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert body["phone"] == "555-0100"
        assert body["first_name"] == "John"
        assert "customer_id" in body
        mock_customers_table.put_item.assert_called_once()

    def test_create_customer_invalid_data(self, mock_customers_table):
        """Test POST /customers with invalid data returns error."""
        event = {
            "httpMethod": "POST",
            "path": "/customers",
            "body": json.dumps(
                {
                    "first_name": "John",
                    # Missing required fields
                }
            ),
        }

        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "error" in body

    def test_get_customer_by_id_success(self, mock_customers_table):
        """Test GET /customers/{id} returns customer."""
        mock_customers_table.scan.return_value = {
            "Items": [
                {
                    "customer_id": "cust-001",
                    "phone": "555-0100",
                    "first_name": "John",
                }
            ]
        }

        event = {
            "httpMethod": "GET",
            "path": "/customers/cust-001",
            "pathParameters": {"customerId": "cust-001"},
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["customer_id"] == "cust-001"

    def test_get_customer_not_found(self, mock_customers_table):
        """Test GET /customers/{id} returns 404 for unknown customer."""
        mock_customers_table.scan.return_value = {"Items": []}

        event = {
            "httpMethod": "GET",
            "path": "/customers/cust-999",
            "pathParameters": {"customerId": "cust-999"},
        }

        response = handler(event, None)

        assert response["statusCode"] == 404


class TestCaseEndpoints:
    """Tests for case API endpoints."""

    @pytest.fixture
    def mock_cases_table(self):
        """Create mock cases table."""
        with patch("index.cases_table") as mock_table:
            yield mock_table

    def test_create_case_success(self, mock_cases_table):
        """Test POST /cases creates case."""
        event = {
            "httpMethod": "POST",
            "path": "/cases",
            "body": json.dumps(
                {
                    "customer_id": "cust-001",
                    "subject": "Billing Issue",
                    "description": "Double charged",
                    "category": "billing",
                    "priority": "high",
                }
            ),
        }

        response = handler(event, None)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert body["customer_id"] == "cust-001"
        assert body["subject"] == "Billing Issue"
        assert body["case_id"].startswith("TICKET-")
        mock_cases_table.put_item.assert_called_once()

    def test_get_customer_cases_success(self, mock_cases_table):
        """Test GET /customers/{id}/cases returns cases."""
        mock_cases_table.query.return_value = {
            "Items": [
                {
                    "case_id": "TICKET-2026-00001",
                    "customer_id": "cust-001",
                    "subject": "Billing Issue",
                    "status": "open",
                }
            ]
        }

        event = {
            "httpMethod": "GET",
            "path": "/customers/cust-001/cases",
            "pathParameters": {"customerId": "cust-001"},
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert len(body) == 1
        assert body[0]["case_id"] == "TICKET-2026-00001"

    def test_add_case_note_success(self, mock_cases_table):
        """Test POST /cases/{id}/notes adds note."""
        mock_cases_table.scan.return_value = {
            "Items": [
                {
                    "case_id": "TICKET-2026-00001",
                    "customer_id": "cust-001",
                    "notes": [],
                }
            ]
        }

        event = {
            "httpMethod": "POST",
            "path": "/cases/TICKET-2026-00001/notes",
            "pathParameters": {"caseId": "TICKET-2026-00001"},
            "body": json.dumps(
                {
                    "content": "Customer called about issue",
                    "author": "agent",
                }
            ),
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        mock_cases_table.update_item.assert_called_once()


class TestAdminEndpoints:
    """Tests for admin endpoints."""

    @pytest.fixture
    def mock_tables(self):
        """Create mock tables."""
        with (
            patch("index.customers_table") as mock_customers,
            patch("index.cases_table") as mock_cases,
            patch("index.interactions_table") as mock_interactions,
        ):
            yield mock_customers, mock_cases, mock_interactions

    def test_seed_data_success(self, mock_tables):
        """Test POST /admin/seed creates demo data."""
        mock_customers, mock_cases, _ = mock_tables

        event = {
            "httpMethod": "POST",
            "path": "/admin/seed",
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["customers_seeded"] == 3
        assert body["cases_seeded"] == 2
        assert mock_customers.put_item.call_count == 3
        assert mock_cases.put_item.call_count == 2

    def test_reset_data_success(self, mock_tables):
        """Test DELETE /admin/reset clears all data."""
        mock_customers, mock_cases, mock_interactions = mock_tables

        mock_customers.scan.return_value = {
            "Items": [{"customer_id": "cust-001", "phone": "555-0100"}]
        }
        mock_cases.scan.return_value = {
            "Items": [{"case_id": "TICKET-2026-00001", "customer_id": "cust-001"}]
        }
        mock_interactions.scan.return_value = {"Items": []}

        event = {
            "httpMethod": "DELETE",
            "path": "/admin/reset",
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["customers_deleted"] == 1
        assert body["cases_deleted"] == 1


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_json_body(self):
        """Test handler with invalid JSON body."""
        event = {
            "httpMethod": "POST",
            "path": "/customers",
            "body": "not valid json",
        }

        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "Invalid JSON" in body["error"]

    def test_unknown_route(self):
        """Test handler with unknown route."""
        event = {
            "httpMethod": "GET",
            "path": "/unknown-route",
        }

        response = handler(event, None)

        assert response["statusCode"] == 404

    def test_cors_preflight(self):
        """Test CORS preflight request."""
        event = {
            "httpMethod": "OPTIONS",
            "path": "/customers",
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        assert "Access-Control-Allow-Origin" in response["headers"]


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self):
        """Test GET /health returns healthy status."""
        event = {
            "httpMethod": "GET",
            "path": "/health",
        }

        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "healthy"
        assert "tables" in body
