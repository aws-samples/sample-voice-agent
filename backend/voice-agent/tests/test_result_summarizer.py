"""Tests for the tool result summarizer module."""

import pytest

try:
    from app.tools.result_summarizer import (
        redact_pii,
        summarize_tool_result,
        _truncate,
        _extract_kb_summary,
        _extract_crm_summary,
        _extract_appointment_summary,
        _extract_time_summary,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


# =============================================================================
# PII Redaction Tests
# =============================================================================


class TestRedactPii:
    """Tests for PII pattern redaction."""

    def test_redact_email(self):
        text = "Contact user@example.com for details"
        result = redact_pii(text)
        assert "user@example.com" not in result
        assert "***@***.***" in result

    def test_redact_phone_dashed(self):
        text = "Call 555-123-4567 for support"
        result = redact_pii(text)
        assert "555-123-4567" not in result
        assert "***-***-****" in result

    def test_redact_phone_dotted(self):
        text = "Call 555.123.4567 for support"
        result = redact_pii(text)
        assert "555.123.4567" not in result

    def test_redact_phone_with_country_code(self):
        text = "Call +1-555-123-4567 for support"
        result = redact_pii(text)
        assert "4567" not in result

    def test_redact_ssn(self):
        text = "SSN is 123-45-6789"
        result = redact_pii(text)
        assert "123-45-6789" not in result
        assert "***-**-****" in result

    def test_redact_account_number(self):
        text = "Account ACCT-12345678 found"
        result = redact_pii(text)
        assert "12345678" not in result
        assert "ACCT-********" in result

    def test_redact_account_number_case_insensitive(self):
        text = "Account acct-12345678 found"
        result = redact_pii(text)
        assert "12345678" not in result

    def test_redact_credit_card(self):
        text = "Card 4111-1111-1111-1111 on file"
        result = redact_pii(text)
        assert "4111" not in result
        assert "****-****-****-****" in result

    def test_no_pii_unchanged(self):
        text = "The weather is sunny today"
        result = redact_pii(text)
        assert result == text

    def test_multiple_pii_patterns(self):
        text = "Email: test@mail.com, Phone: 555-123-4567"
        result = redact_pii(text)
        assert "test@mail.com" not in result
        assert "555-123-4567" not in result

    def test_empty_string(self):
        assert redact_pii("") == ""


# =============================================================================
# Truncation Tests
# =============================================================================


class TestTruncate:
    """Tests for string truncation."""

    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_exact_length_unchanged(self):
        text = "x" * 100
        assert _truncate(text, 100) == text

    def test_long_text_truncated(self):
        text = "x" * 200
        result = _truncate(text, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_truncation_at_boundary(self):
        text = "x" * 503
        result = _truncate(text, 500)
        assert len(result) == 500
        assert result[-3:] == "..."
        assert result[:497] == "x" * 497


# =============================================================================
# Type-Specific Extractor Tests
# =============================================================================


class TestKbExtractor:
    """Tests for KB search result extraction."""

    def test_string_response(self):
        response = "Line one\nLine two\nLine three\nLine four\nLine five"
        result = _extract_kb_summary(response)
        assert result is not None
        assert "KB result:" in result
        assert "Line one" in result
        assert "+2 more lines" in result

    def test_dict_with_documents(self):
        content = {
            "documents": [
                {"title": "Doc A", "confidence": 0.95, "snippet": "First doc"},
                {"title": "Doc B", "confidence": 0.80, "snippet": "Second doc"},
            ]
        }
        result = _extract_kb_summary(content)
        assert result is not None
        assert "KB results:" in result
        assert "Doc A" in result
        assert "0.95" in result
        assert "Doc B" in result

    def test_dict_no_documents_returns_none(self):
        result = _extract_kb_summary({"other": "data"})
        assert result is None

    def test_empty_string(self):
        result = _extract_kb_summary("")
        assert result is None


class TestCrmExtractor:
    """Tests for CRM lookup result extraction."""

    def test_dict_with_customer_fields(self):
        content = {
            "customer_id": "CUST-001",
            "verified": True,
            "name": "Jane Doe",
            "status": "active",
        }
        result = _extract_crm_summary(content)
        assert result is not None
        assert "CRM:" in result
        assert "CUST-001" in result
        assert "verified=True" in result
        assert "Jane Doe" in result

    def test_string_response(self):
        response = "Customer verified successfully\nID: CUST-001"
        result = _extract_crm_summary(response)
        assert result is not None
        assert "CRM result:" in result

    def test_empty_dict_returns_none(self):
        result = _extract_crm_summary({})
        assert result is None


class TestAppointmentExtractor:
    """Tests for appointment result extraction."""

    def test_dict_with_appointment_fields(self):
        content = {
            "appointment_id": "APT-123",
            "date": "2026-03-10",
            "time": "14:00",
            "type": "checkup",
            "status": "confirmed",
        }
        result = _extract_appointment_summary(content)
        assert result is not None
        assert "Appointment:" in result
        assert "APT-123" in result
        assert "2026-03-10" in result
        assert "14:00" in result
        assert "checkup" in result

    def test_string_response(self):
        response = "Appointment booked for March 10"
        result = _extract_appointment_summary(response)
        assert result is not None
        assert "Appointment result:" in result

    def test_empty_dict_returns_none(self):
        result = _extract_appointment_summary({})
        assert result is None


class TestTimeExtractor:
    """Tests for time tool result extraction."""

    def test_dict_with_time_fields(self):
        content = {
            "current_time": "02:30 PM",
            "current_date": "Monday, January 27, 2026",
        }
        result = _extract_time_summary(content)
        assert result is not None
        assert "Time:" in result
        assert "02:30 PM" in result
        assert "Monday, January 27, 2026" in result

    def test_time_only(self):
        content = {"current_time": "14:30"}
        result = _extract_time_summary(content)
        assert result is not None
        assert "14:30" in result

    def test_empty_dict_returns_none(self):
        result = _extract_time_summary({})
        assert result is None


# =============================================================================
# summarize_tool_result Tests
# =============================================================================


class TestSummarizeToolResult:
    """Tests for the main summarize_tool_result function."""

    def test_none_content_returns_none(self):
        result = summarize_tool_result(None)
        assert result is None

    def test_dict_content_generic(self):
        content = {"key": "value", "count": 42}
        result = summarize_tool_result(content)
        assert result is not None
        assert "key" in result
        assert "value" in result

    def test_string_content(self):
        result = summarize_tool_result("simple response text")
        assert result == "simple response text"

    def test_truncation_applied(self):
        long_text = "x" * 1000
        result = summarize_tool_result(long_text, max_chars=100)
        assert result is not None
        assert len(result) <= 100
        assert result.endswith("...")

    def test_pii_redacted_in_output(self):
        content = {"email": "user@example.com", "phone": "555-123-4567"}
        result = summarize_tool_result(content)
        assert result is not None
        assert "user@example.com" not in result
        assert "555-123-4567" not in result

    def test_known_tool_uses_specific_extractor(self):
        content = {
            "current_time": "02:30 PM",
            "current_date": "Monday, March 5, 2026",
        }
        result = summarize_tool_result(content, tool_name="get_current_time")
        assert result is not None
        assert "Time:" in result
        assert "02:30 PM" in result

    def test_kb_tool_uses_kb_extractor(self):
        content = "Knowledge base returned:\nDoc title A\nDoc title B"
        result = summarize_tool_result(content, tool_name="search_knowledge_base")
        assert result is not None
        assert "KB result:" in result

    def test_unknown_tool_uses_generic(self):
        content = {"data": "something"}
        result = summarize_tool_result(content, tool_name="unknown_tool")
        assert result is not None
        assert "data" in result

    def test_max_chars_respected(self):
        content = {"long_field": "x" * 1000}
        result = summarize_tool_result(content, max_chars=50)
        assert result is not None
        assert len(result) <= 50

    def test_pii_in_appointment_redacted(self):
        content = "Appointment booked for user@example.com at 555-123-4567"
        result = summarize_tool_result(content, tool_name="book_appointment")
        assert result is not None
        assert "user@example.com" not in result
        assert "555-123-4567" not in result
