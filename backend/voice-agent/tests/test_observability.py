"""
Tests for observability features: correlation IDs, call summaries, and error categorization.

Run with: pytest tests/test_observability.py -v
"""

import pytest

try:
    from app.service_main import ErrorCategory, categorize_error
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog/aiohttp/pipecat)",
        allow_module_level=True,
    )


class TestErrorCategorization:
    """Tests for error categorization logic."""

    def test_stt_error_by_provider(self):
        """Test STT error detection by provider name."""
        error = Exception("Deepgram API returned 401 unauthorized")
        assert categorize_error(error) == ErrorCategory.STT

    def test_stt_error_by_keyword(self):
        """Test STT error detection by keyword."""
        error = Exception("Failed to transcribe audio")
        assert categorize_error(error) == ErrorCategory.STT

    def test_llm_error_by_provider(self):
        """Test LLM error detection by provider name."""
        error = Exception("Bedrock throttling exception")
        assert categorize_error(error) == ErrorCategory.LLM

    def test_llm_error_by_model(self):
        """Test LLM error detection by model name."""
        error = Exception("Claude model invocation failed")
        assert categorize_error(error) == ErrorCategory.LLM

    def test_tts_error_by_provider(self):
        """Test TTS error detection by provider name."""
        error = Exception("Cartesia voice synthesis timeout")
        assert categorize_error(error) == ErrorCategory.TTS

    def test_tts_error_by_keyword(self):
        """Test TTS error detection by keyword."""
        error = Exception("Text-to-speech service unavailable")
        assert categorize_error(error) == ErrorCategory.TTS

    def test_transport_error_by_provider(self):
        """Test transport error detection by provider name."""
        error = Exception("Daily transport connection lost")
        assert categorize_error(error) == ErrorCategory.TRANSPORT

    def test_transport_error_by_keyword(self):
        """Test transport error detection by keyword."""
        error = Exception("WebRTC peer connection failed")
        assert categorize_error(error) == ErrorCategory.TRANSPORT

    def test_transport_error_network(self):
        """Test transport error detection for network issues."""
        error = Exception("Network connection timeout")
        assert categorize_error(error) == ErrorCategory.TRANSPORT

    def test_config_error_by_keyword(self):
        """Test config error detection."""
        error = Exception("API_KEY environment variable required")
        assert categorize_error(error) == ErrorCategory.CONFIG

    def test_config_error_missing(self):
        """Test config error detection for missing values."""
        error = Exception("Missing required configuration")
        assert categorize_error(error) == ErrorCategory.CONFIG

    def test_unknown_error(self):
        """Test that unrecognized errors are categorized as unknown."""
        error = Exception("Something unexpected happened")
        assert categorize_error(error) == ErrorCategory.UNKNOWN

    def test_error_type_detection(self):
        """Test error categorization by exception type name."""

        class DeepgramError(Exception):
            pass

        error = DeepgramError("API error")
        assert categorize_error(error) == ErrorCategory.STT

    def test_case_insensitive(self):
        """Test that error matching is case-insensitive."""
        error = Exception("DEEPGRAM API ERROR")
        assert categorize_error(error) == ErrorCategory.STT


class TestErrorCategoryConstants:
    """Tests for ErrorCategory constants."""

    def test_category_values(self):
        """Test that error categories have expected string values."""
        assert ErrorCategory.STT == "stt_error"
        assert ErrorCategory.LLM == "llm_error"
        assert ErrorCategory.TTS == "tts_error"
        assert ErrorCategory.TRANSPORT == "transport_error"
        assert ErrorCategory.CONFIG == "config_error"
        assert ErrorCategory.UNKNOWN == "unknown_error"

    def test_all_categories_unique(self):
        """Test that all error categories are unique."""
        categories = [
            ErrorCategory.STT,
            ErrorCategory.LLM,
            ErrorCategory.TTS,
            ErrorCategory.TRANSPORT,
            ErrorCategory.CONFIG,
            ErrorCategory.UNKNOWN,
        ]
        assert len(categories) == len(set(categories))
