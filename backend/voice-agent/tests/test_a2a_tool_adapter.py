"""Tests for A2A to Pipecat tool adapter."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

try:
    from app.a2a.tool_adapter import (
        create_a2a_tool_handler,
        extract_text_from_result,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


def _make_params(
    *,
    function_name: str = "test_tool",
    tool_call_id: str = "tc-123",
    args: dict | None = None,
    result_callback: AsyncMock | None = None,
) -> MagicMock:
    """Create a mock FunctionCallParams object."""
    params = MagicMock()
    params.function_name = function_name
    params.tool_call_id = tool_call_id
    params.arguments = args if args is not None else {}
    params.llm = MagicMock()
    params.context = MagicMock()
    params.result_callback = result_callback or AsyncMock()
    return params


def _make_agent_result(text: str = "Mock response") -> MagicMock:
    """Create a mock AgentResult matching Strands SDK structure."""
    result = MagicMock()
    result.message = {
        "role": "assistant",
        "content": [{"text": text}],
    }
    return result


def _make_multi_block_result(texts: list[str]) -> MagicMock:
    """Create a mock AgentResult with multiple text blocks."""
    result = MagicMock()
    result.message = {
        "role": "assistant",
        "content": [{"text": t} for t in texts],
    }
    return result


class TestExtractTextFromResult:
    """Tests for extract_text_from_result."""

    def test_single_text_block(self):
        result = _make_agent_result("Hello from KB agent")
        text = extract_text_from_result(result)
        assert text == "Hello from KB agent"

    def test_multiple_text_blocks(self):
        result = _make_multi_block_result(["Part 1.", "Part 2."])
        text = extract_text_from_result(result)
        assert text == "Part 1.\nPart 2."

    def test_empty_content(self):
        result = MagicMock()
        result.message = {"role": "assistant", "content": []}
        text = extract_text_from_result(result)
        assert text == ""

    def test_no_message(self):
        result = MagicMock(spec=[])
        del result.message
        text = extract_text_from_result(result)
        # Falls back to str(result)
        assert isinstance(text, str)

    def test_non_dict_message(self):
        result = MagicMock()
        result.message = "just a string"
        text = extract_text_from_result(result)
        assert text == "just a string"

    def test_mixed_content_blocks(self):
        """Test with non-text content blocks mixed in."""
        result = MagicMock()
        result.message = {
            "role": "assistant",
            "content": [
                {"text": "Text block"},
                {"image": "data:image/png;base64,..."},  # Non-text block
                {"text": "Another text block"},
            ],
        }
        text = extract_text_from_result(result)
        assert text == "Text block\nAnother text block"

    def test_none_message(self):
        result = MagicMock()
        result.message = None
        text = extract_text_from_result(result)
        assert isinstance(text, str)


class TestCreateA2AToolHandler:
    """Tests for create_a2a_tool_handler."""

    @pytest.mark.asyncio
    async def test_successful_invocation(self):
        """Test successful A2A tool call."""
        mock_agent = AsyncMock()
        mock_agent.invoke_async.return_value = _make_agent_result(
            "Our return policy allows returns within 30 days."
        )

        handler = create_a2a_tool_handler("search_knowledge_base", mock_agent)
        result_callback = AsyncMock()
        params = _make_params(
            function_name="search_knowledge_base",
            args={"query": "What is the return policy?"},
            result_callback=result_callback,
        )

        await handler(params)

        # Verify agent was called
        mock_agent.invoke_async.assert_called_once_with("What is the return policy?")

        # Verify result_callback was called with extracted text
        result_callback.assert_called_once()
        call_args = result_callback.call_args[0][0]
        assert "return policy" in call_args.lower()

    @pytest.mark.asyncio
    async def test_empty_query_fallback(self):
        """Test fallback when query param is empty."""
        mock_agent = AsyncMock()
        mock_agent.invoke_async.return_value = _make_agent_result("Response")

        handler = create_a2a_tool_handler("some_skill", mock_agent)
        result_callback = AsyncMock()
        params = _make_params(
            function_name="some_skill",
            args={"context": "some context", "detail": "some detail"},
            result_callback=result_callback,
        )

        await handler(params)

        # Should concatenate non-query args as fallback
        call_args = mock_agent.invoke_async.call_args[0][0]
        assert "some context" in call_args
        assert "some detail" in call_args

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Test timeout produces error result."""
        mock_agent = AsyncMock()

        async def slow_invoke(query):
            await asyncio.sleep(10)  # Will be cancelled by timeout

        mock_agent.invoke_async.side_effect = slow_invoke

        handler = create_a2a_tool_handler(
            "search_knowledge_base",
            mock_agent,
            timeout_seconds=0.1,  # Very short timeout
        )
        result_callback = AsyncMock()
        params = _make_params(
            function_name="search_knowledge_base",
            args={"query": "test"},
            result_callback=result_callback,
        )

        await handler(params)

        # Should return error dict
        result_callback.assert_called_once()
        error_result = result_callback.call_args[0][0]
        assert isinstance(error_result, dict)
        assert error_result["error"] is True
        assert error_result["error_code"] == "A2A_TIMEOUT"

    @pytest.mark.asyncio
    async def test_exception_handling(self):
        """Test general exception produces error result."""
        mock_agent = AsyncMock()
        mock_agent.invoke_async.side_effect = ConnectionError("Connection refused")

        handler = create_a2a_tool_handler("search_knowledge_base", mock_agent)
        result_callback = AsyncMock()
        params = _make_params(
            function_name="search_knowledge_base",
            args={"query": "test"},
            result_callback=result_callback,
        )

        await handler(params)

        # Should return error dict
        result_callback.assert_called_once()
        error_result = result_callback.call_args[0][0]
        assert isinstance(error_result, dict)
        assert error_result["error"] is True
        assert error_result["error_code"] == "A2A_ERROR"
        assert "ConnectionError" in error_result["error_message"]

    @pytest.mark.asyncio
    async def test_cancellation_propagated(self):
        """Test that CancelledError (barge-in) is re-raised."""
        mock_agent = AsyncMock()
        mock_agent.invoke_async.side_effect = asyncio.CancelledError()

        handler = create_a2a_tool_handler("search_knowledge_base", mock_agent)
        result_callback = AsyncMock()
        params = _make_params(
            function_name="search_knowledge_base",
            args={"query": "test"},
            result_callback=result_callback,
        )

        with pytest.raises(asyncio.CancelledError):
            await handler(params)

        # result_callback should NOT have been called
        result_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_metrics_collection(self):
        """Test that metrics are recorded on success."""
        mock_agent = AsyncMock()
        mock_agent.invoke_async.return_value = _make_agent_result("Response")

        mock_collector = MagicMock()

        handler = create_a2a_tool_handler(
            "search_knowledge_base",
            mock_agent,
            collector=mock_collector,
        )
        result_callback = AsyncMock()
        params = _make_params(
            function_name="search_knowledge_base",
            args={"query": "test"},
            result_callback=result_callback,
        )

        await handler(params)

        mock_collector.record_tool_execution.assert_called_once()
        call_kwargs = mock_collector.record_tool_execution.call_args
        assert call_kwargs[1]["tool_name"] == "search_knowledge_base"
        assert call_kwargs[1]["category"] == "a2a"
        assert call_kwargs[1]["status"] == "success"
        assert call_kwargs[1]["execution_time_ms"] > 0

    @pytest.mark.asyncio
    async def test_metrics_error_does_not_fail_tool(self):
        """Test that metrics errors don't break tool execution."""
        mock_agent = AsyncMock()
        mock_agent.invoke_async.return_value = _make_agent_result("Response")

        mock_collector = MagicMock()
        mock_collector.record_tool_execution.side_effect = Exception("Metrics error")

        handler = create_a2a_tool_handler(
            "search_knowledge_base",
            mock_agent,
            collector=mock_collector,
        )
        result_callback = AsyncMock()
        params = _make_params(
            function_name="search_knowledge_base",
            args={"query": "test"},
            result_callback=result_callback,
        )

        # Should NOT raise, despite metrics failure
        await handler(params)

        # Result callback should still be called with the actual result
        result_callback.assert_called_once()
        assert "Response" in result_callback.call_args[0][0]
