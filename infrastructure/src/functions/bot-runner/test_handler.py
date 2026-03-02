"""
Unit tests for Bot Runner Lambda handler.

Run with: pytest test_handler.py -v
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

# Set environment variables before importing handler
os.environ["DAILY_API_KEY_SECRET_ARN"] = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:test-secret"
)

import handler


class TestStartSession(unittest.TestCase):
    """Tests for start_session handler."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_context = MagicMock()
        self.mock_context.aws_request_id = "test-request-id"

    def _make_event(self, body: dict) -> dict:
        """Create API Gateway event with body."""
        return {
            "body": json.dumps(body),
            "headers": {"Content-Type": "application/json"},
            "httpMethod": "POST",
            "path": "/start",
        }

    def test_missing_call_id_returns_400(self):
        """Should return 400 when callId is missing."""
        event = self._make_event(
            {
                "callDomain": "test.daily.co",
                "from": "+15551234567",
            }
        )

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertIn("callId", body["error"])

    def test_missing_call_domain_returns_400(self):
        """Should return 400 when callDomain is missing."""
        event = self._make_event(
            {
                "callId": "test-call-123",
                "from": "+15551234567",
            }
        )

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertIn("callDomain", body["error"])

    def test_invalid_json_returns_400(self):
        """Should return 400 for invalid JSON body."""
        event = {
            "body": "not valid json {{{",
            "headers": {"Content-Type": "application/json"},
        }

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 400)
        body = json.loads(response["body"])
        self.assertIn("Invalid JSON", body["error"])

    @patch("handler.EcsServiceClient")
    @patch("handler.DailyClient")
    def test_successful_session_start(self, mock_daily_cls, mock_service_cls):
        """Should return 200 and session details on success."""
        # Set up mocks
        mock_daily = MagicMock()
        mock_daily.create_room.return_value = {
            "url": "https://test.daily.co/voice-test-123",
            "name": "voice-test-123",
            "id": "room-id-abc",
        }
        mock_daily.create_meeting_token.return_value = "test-token-xyz"
        mock_daily.get_sip_uri.return_value = "sip:room-id-abc@sip.daily.co"
        mock_daily_cls.return_value = mock_daily

        mock_service = MagicMock()
        mock_service.start_call.return_value = {"status": "started"}
        mock_service_cls.return_value = mock_service

        event = self._make_event(
            {
                "callId": "test-call-123",
                "callDomain": "test.daily.co",
                "from": "+15551234567",
            }
        )

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 200)
        body = json.loads(response["body"])
        self.assertEqual(body["status"], "started")
        self.assertIn("sessionId", body)
        self.assertIn("roomUrl", body)
        self.assertIn("sipUri", body)

    @patch("handler.EcsServiceClient")
    @patch("handler.DailyClient")
    def test_daily_api_error_returns_500(self, mock_daily_cls, mock_service_cls):
        """Should return 500 when Daily API fails."""
        mock_daily = MagicMock()
        mock_daily.create_room.side_effect = ValueError("Daily API error: 401")
        mock_daily_cls.return_value = mock_daily

        event = self._make_event(
            {
                "callId": "test-call-123",
                "callDomain": "test.daily.co",
                "from": "+15551234567",
            }
        )

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 500)

    @patch("handler.EcsServiceClient")
    @patch("handler.DailyClient")
    def test_ecs_service_error_returns_500(self, mock_daily_cls, mock_service_cls):
        """Should return 500 when ECS service fails."""
        mock_daily = MagicMock()
        mock_daily.create_room.return_value = {
            "url": "https://test.daily.co/voice-test-123",
            "name": "voice-test-123",
            "id": "room-id-abc",
        }
        mock_daily.create_meeting_token.return_value = "test-token-xyz"
        mock_daily.get_sip_uri.return_value = "sip:room-id-abc@sip.daily.co"
        mock_daily_cls.return_value = mock_daily

        mock_service = MagicMock()
        mock_service.start_call.side_effect = Exception("ECS service error")
        mock_service_cls.return_value = mock_service

        event = self._make_event(
            {
                "callId": "test-call-123",
                "callDomain": "test.daily.co",
                "from": "+15551234567",
            }
        )

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 500)

    def test_empty_body_returns_400(self):
        """Should return 400 when body is empty."""
        event = {"body": "{}"}

        response = handler.start_session(event, self.mock_context)

        self.assertEqual(response["statusCode"], 400)

    @patch("handler.EcsServiceClient")
    @patch("handler.DailyClient")
    def test_session_id_format(self, mock_daily_cls, mock_service_cls):
        """Session ID should include call ID prefix."""
        mock_daily = MagicMock()
        mock_daily.create_room.return_value = {
            "url": "https://test.daily.co/voice-test-123",
            "name": "voice-test-123",
            "id": "room-id-abc",
        }
        mock_daily.create_meeting_token.return_value = "test-token-xyz"
        mock_daily.get_sip_uri.return_value = "sip:room-id-abc@sip.daily.co"
        mock_daily_cls.return_value = mock_daily

        mock_service = MagicMock()
        mock_service.start_call.return_value = {"status": "started"}
        mock_service_cls.return_value = mock_service

        event = self._make_event(
            {
                "callId": "my-call-id",
                "callDomain": "test.daily.co",
                "from": "+15551234567",
            }
        )

        response = handler.start_session(event, self.mock_context)
        body = json.loads(response["body"])

        self.assertTrue(body["sessionId"].startswith("voice-my-call-id-"))


class TestParseBody(unittest.TestCase):
    """Tests for _parse_body helper."""

    def test_parses_json_string(self):
        """Should parse JSON string body."""
        event = {"body": '{"key": "value"}'}
        result = handler._parse_body(event)
        self.assertEqual(result, {"key": "value"})

    def test_handles_dict_body(self):
        """Should handle dict body (already parsed)."""
        event = {"body": {"key": "value"}}
        result = handler._parse_body(event)
        self.assertEqual(result, {"key": "value"})

    def test_handles_empty_body(self):
        """Should return empty dict for missing body."""
        event = {}
        result = handler._parse_body(event)
        self.assertEqual(result, {})

    def test_raises_on_invalid_json(self):
        """Should raise ValueError for invalid JSON."""
        event = {"body": "not json"}
        with self.assertRaises(ValueError):
            handler._parse_body(event)


class TestResponseHelpers(unittest.TestCase):
    """Tests for response helper functions."""

    def test_success_response_format(self):
        """Success response should have correct format."""
        response = handler._success_response(200, {"key": "value"})

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        self.assertIn("Access-Control-Allow-Origin", response["headers"])
        body = json.loads(response["body"])
        self.assertEqual(body["key"], "value")

    def test_error_response_format(self):
        """Error response should have correct format."""
        response = handler._error_response(400, "Test error")

        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(response["headers"]["Content-Type"], "application/json")
        body = json.loads(response["body"])
        self.assertEqual(body["error"], "Test error")
        self.assertEqual(body["status"], "error")


class TestGetSystemPrompt(unittest.TestCase):
    """Tests for _get_system_prompt helper."""

    def test_returns_non_empty_prompt(self):
        """Should return a non-empty system prompt."""
        prompt = handler._get_system_prompt("+15551234567")
        self.assertTrue(len(prompt) > 0)

    def test_prompt_contains_assistant_context(self):
        """Prompt should contain assistant context."""
        prompt = handler._get_system_prompt("+15551234567")
        self.assertIn("assistant", prompt.lower())

    def test_prompt_contains_tool_usage_guidance(self):
        """Prompt should contain tool usage guidance for clean context aggregation."""
        prompt = handler._get_system_prompt("+15551234567")
        # Tool usage guidance prevents LLM from outputting text before tool calls,
        # which would cause context aggregation issues with concurrent text/tool frames
        self.assertIn("tool", prompt.lower())
        self.assertIn("directly", prompt.lower())


if __name__ == "__main__":
    unittest.main()
