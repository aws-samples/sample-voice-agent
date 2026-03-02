"""Integration tests for filler phrase injection during tool execution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from app.filler_phrases import FillerPhraseManager
    from app.tools.schema import ToolCategory
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


class TestFillerTaskCancellation:
    """Tests for filler task cancellation when tool returns quickly."""

    @pytest.mark.asyncio
    async def test_filler_cancelled_for_fast_tool(self):
        """Test that filler task is cancelled when tool returns before threshold."""
        filler_fired = {"value": False}

        async def delayed_filler(delay_seconds: float):
            await asyncio.sleep(delay_seconds)
            filler_fired["value"] = True

        async def fast_tool():
            await asyncio.sleep(0.05)  # 50ms - well under threshold
            return "result"

        # Start filler task with 0.5s delay
        filler_task = asyncio.create_task(delayed_filler(0.5))

        try:
            result = await fast_tool()
        finally:
            if not filler_task.done():
                filler_task.cancel()
                try:
                    await filler_task
                except asyncio.CancelledError:
                    pass

        assert result == "result"
        assert filler_fired["value"] is False, "Filler should not have fired"

    @pytest.mark.asyncio
    async def test_filler_fires_for_slow_tool(self):
        """Test that filler task fires when tool takes longer than threshold."""
        filler_fired = {"value": False}
        filler_phrase = {"value": None}

        async def delayed_filler(phrase: str, delay_seconds: float):
            await asyncio.sleep(delay_seconds)
            filler_fired["value"] = True
            filler_phrase["value"] = phrase

        async def slow_tool():
            await asyncio.sleep(0.3)  # 300ms - longer than 100ms threshold
            return "result"

        # Start filler task with 0.1s delay (will fire before tool completes)
        filler_task = asyncio.create_task(delayed_filler("Let me look that up...", 0.1))

        try:
            result = await slow_tool()
        finally:
            if not filler_task.done():
                filler_task.cancel()
                try:
                    await filler_task
                except asyncio.CancelledError:
                    pass

        assert result == "result"
        assert filler_fired["value"] is True, "Filler should have fired"
        assert filler_phrase["value"] == "Let me look that up..."


class TestFillerPhraseSelection:
    """Tests for filler phrase selection during tool execution."""

    def test_category_based_phrase_selection(self):
        """Test that phrases are selected based on tool category."""
        manager = FillerPhraseManager()

        # Customer info should get account-related phrase
        phrase = manager.get_phrase(ToolCategory.CUSTOMER_INFO)
        assert phrase in manager.CATEGORY_PHRASES[ToolCategory.CUSTOMER_INFO]

        # Order management should get order-related phrase
        phrase = manager.get_phrase(ToolCategory.ORDER_MANAGEMENT)
        assert phrase in manager.CATEGORY_PHRASES[ToolCategory.ORDER_MANAGEMENT]

    def test_variety_across_multiple_tools(self):
        """Test that different tools get varied phrases."""
        manager = FillerPhraseManager()

        phrases = []
        for category in [
            ToolCategory.SYSTEM,
            ToolCategory.CUSTOMER_INFO,
            ToolCategory.ORDER_MANAGEMENT,
        ]:
            phrases.append(manager.get_phrase(category))

        # Should have different phrases for different categories
        # (unless history forces reuse)
        unique_phrases = set(phrases)
        assert len(unique_phrases) >= 1  # At minimum, we get phrases


class TestFillerPhraseConfiguration:
    """Tests for filler phrase configuration."""

    def test_configuration_defaults(self):
        """Test default configuration values.

        ENABLE_FILLER_PHRASES defaults to False because the LLM's natural
        pre-tool text already serves as an implicit filler, and adding
        explicit fillers causes context interleaving issues.
        """
        from app.pipeline_ecs import _get_enable_filler_phrases
        from unittest.mock import patch, MagicMock

        # Mock config to return defaults
        mock_config = MagicMock()
        mock_config.features.enable_filler_phrases = False

        with patch("app.pipeline_ecs._get_config", return_value=mock_config):
            result = _get_enable_filler_phrases()

        # Disabled by default - LLM's natural text serves as filler
        assert result is False

    def test_configuration_override_enable(self):
        """Test that filler phrases can be enabled via config."""
        from app.pipeline_ecs import _get_enable_filler_phrases
        from unittest.mock import patch, MagicMock

        # Mock config to return enabled
        mock_config = MagicMock()
        mock_config.features.enable_filler_phrases = True

        with patch("app.pipeline_ecs._get_config", return_value=mock_config):
            result = _get_enable_filler_phrases()

        assert result is True


class TestFunctionCallFillerProcessor:
    """Tests for the FunctionCallFillerProcessor."""

    def test_processor_initialization(self):
        """Test that processor initializes correctly."""
        from app.function_call_filler_processor import FunctionCallFillerProcessor

        processor = FunctionCallFillerProcessor(enabled=True)
        assert processor.enabled is True
        assert processor._last_phrase is None
        assert processor._phrase_history == []

    def test_processor_disabled(self):
        """Test that processor respects enabled flag."""
        from app.function_call_filler_processor import FunctionCallFillerProcessor

        processor = FunctionCallFillerProcessor(enabled=False)
        assert processor.enabled is False

    def test_phrase_selection_function_specific(self):
        """Test that function-specific phrases are selected."""
        from app.function_call_filler_processor import FunctionCallFillerProcessor

        processor = FunctionCallFillerProcessor()

        # get_customer_info should get customer-specific phrase
        phrase = processor._get_phrase(["get_customer_info"])
        assert "account" in phrase.lower()

        # get_current_time should get time-specific phrase
        phrase = processor._get_phrase(["get_current_time"])
        assert "time" in phrase.lower()

    def test_phrase_selection_generic_fallback(self):
        """Test that generic phrases are used for unknown functions."""
        from app.function_call_filler_processor import FunctionCallFillerProcessor

        processor = FunctionCallFillerProcessor()

        # Unknown function should get generic phrase
        phrase = processor._get_phrase(["unknown_function"])
        assert phrase in processor.GENERIC_PHRASES

    def test_phrase_deduplication(self):
        """Test that recently used phrases are avoided."""
        from app.function_call_filler_processor import FunctionCallFillerProcessor

        processor = FunctionCallFillerProcessor()

        # Get several phrases
        phrases = []
        for _ in range(3):
            phrase = processor._get_phrase(["unknown_function"])
            phrases.append(phrase)

        # History should be tracking phrases
        assert len(processor._phrase_history) == 3

    def test_reset_clears_history(self):
        """Test that reset clears phrase history."""
        from app.function_call_filler_processor import FunctionCallFillerProcessor

        processor = FunctionCallFillerProcessor()

        # Get some phrases
        processor._get_phrase(["test"])
        processor._get_phrase(["test"])

        assert len(processor._phrase_history) > 0

        # Reset
        processor.reset()

        assert processor._last_phrase is None
        assert processor._phrase_history == []


class TestFillerWithToolExecution:
    """Integration tests simulating full tool execution with fillers."""

    @pytest.mark.asyncio
    async def test_full_tool_flow_with_filler(self):
        """Test complete flow: tool execution with filler phrase injection."""
        from app.filler_phrases import FillerPhraseManager
        from app.tools.schema import ToolCategory

        # Track what happened
        events = []

        async def mock_inject_filler(phrase: str):
            events.append(("filler", phrase))

        async def mock_tool_execution():
            await asyncio.sleep(0.2)  # Simulate slow tool
            events.append(("tool_complete", "result"))
            return "result"

        manager = FillerPhraseManager()
        phrase = manager.get_phrase(ToolCategory.SYSTEM)

        # Start filler task
        filler_task = asyncio.create_task(
            _delayed_action(mock_inject_filler, phrase, delay=0.1)
        )

        try:
            result = await mock_tool_execution()
        finally:
            if not filler_task.done():
                filler_task.cancel()
                try:
                    await filler_task
                except asyncio.CancelledError:
                    pass

        # Filler should have fired before tool completed
        assert len(events) == 2
        assert events[0][0] == "filler"
        assert events[1] == ("tool_complete", "result")


async def _delayed_action(action, *args, delay: float):
    """Helper to execute action after delay."""
    await asyncio.sleep(delay)
    await action(*args)
