"""Tests for the tool executor module."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

try:
    from app.tools import (
        ToolCategory,
        ToolContext,
        ToolDefinition,
        ToolExecutor,
        ToolParameter,
        ToolRegistry,
        ToolResult,
        ToolStatus,
        success_result,
        error_result,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def registry():
    """Create a fresh tool registry."""
    return ToolRegistry()


@pytest.fixture
def context():
    """Create a tool context for testing."""
    return ToolContext(
        call_id="test-call-123",
        session_id="test-session-456",
        turn_number=1,
    )


@pytest.fixture
def fast_tool():
    """Create a fast-executing tool."""

    async def executor(args, context):
        return success_result({"echo": args.get("message", "default")})

    return ToolDefinition(
        name="fast_tool",
        description="A fast tool",
        category=ToolCategory.TESTING,
        parameters=[
            ToolParameter(
                name="message",
                type="string",
                description="Message",
                required=False,
            ),
        ],
        executor=executor,
        timeout_seconds=5.0,
    )


@pytest.fixture
def slow_tool():
    """Create a slow-executing tool that will timeout."""

    async def executor(args, context):
        await asyncio.sleep(10)  # Will be cancelled by timeout
        return success_result({"never": "reached"})

    return ToolDefinition(
        name="slow_tool",
        description="A slow tool",
        category=ToolCategory.TESTING,
        parameters=[],
        executor=executor,
        timeout_seconds=0.1,  # Very short timeout
    )


@pytest.fixture
def error_tool():
    """Create a tool that raises an exception."""

    async def executor(args, context):
        raise ValueError("Simulated error")

    return ToolDefinition(
        name="error_tool",
        description="A tool that errors",
        category=ToolCategory.TESTING,
        parameters=[],
        executor=executor,
        timeout_seconds=5.0,
    )


@pytest.fixture
def required_param_tool():
    """Create a tool with required parameters."""

    async def executor(args, context):
        return success_result({"value": args["required_field"]})

    return ToolDefinition(
        name="required_param_tool",
        description="A tool with required params",
        category=ToolCategory.TESTING,
        parameters=[
            ToolParameter(
                name="required_field",
                type="string",
                description="Required field",
                required=True,
            ),
            ToolParameter(
                name="optional_field",
                type="number",
                description="Optional field",
                required=False,
            ),
        ],
        executor=executor,
        timeout_seconds=5.0,
    )


# =============================================================================
# ToolExecutor Tests
# =============================================================================


class TestToolExecutor:
    """Tests for ToolExecutor class."""

    @pytest.mark.asyncio
    async def test_execute_success(self, registry, fast_tool, context):
        """Test successful tool execution."""
        registry.register(fast_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute(
            tool_name="fast_tool",
            arguments={"message": "hello"},
            context=context,
        )

        assert result.status == ToolStatus.SUCCESS
        assert result.content == {"echo": "hello"}
        assert result.execution_time_ms > 0

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool(self, registry, context):
        """Test executing a tool that doesn't exist."""
        executor = ToolExecutor(registry)

        result = await executor.execute(
            tool_name="nonexistent",
            arguments={},
            context=context,
        )

        assert result.status == ToolStatus.ERROR
        assert result.error_code == "TOOL_NOT_FOUND"
        assert "nonexistent" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_timeout(self, registry, slow_tool, context):
        """Test tool execution timeout."""
        registry.register(slow_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute(
            tool_name="slow_tool",
            arguments={},
            context=context,
        )

        assert result.status == ToolStatus.TIMEOUT
        assert result.error_code == "EXECUTION_TIMEOUT"
        assert "0.1" in result.error_message  # Should mention timeout value

    @pytest.mark.asyncio
    async def test_execute_error(self, registry, error_tool, context):
        """Test tool execution with exception."""
        registry.register(error_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute(
            tool_name="error_tool",
            arguments={},
            context=context,
        )

        assert result.status == ToolStatus.ERROR
        assert result.error_code == "ValueError"
        assert "Simulated error" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_missing_required_param(
        self, registry, required_param_tool, context
    ):
        """Test validation of missing required parameter."""
        registry.register(required_param_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute(
            tool_name="required_param_tool",
            arguments={},  # Missing required_field
            context=context,
        )

        assert result.status == ToolStatus.ERROR
        assert result.error_code == "INVALID_ARGUMENTS"
        assert "required_field" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_unknown_param(self, registry, fast_tool, context):
        """Test validation of unknown parameter."""
        registry.register(fast_tool)
        executor = ToolExecutor(registry)

        result = await executor.execute(
            tool_name="fast_tool",
            arguments={"unknown_param": "value"},
            context=context,
        )

        assert result.status == ToolStatus.ERROR
        assert result.error_code == "INVALID_ARGUMENTS"
        assert "unknown_param" in result.error_message

    @pytest.mark.asyncio
    async def test_execute_with_metrics(self, registry, fast_tool, context):
        """Test that metrics are recorded during execution."""
        registry.register(fast_tool)

        mock_collector = MagicMock()
        executor = ToolExecutor(registry, mock_collector)

        result = await executor.execute(
            tool_name="fast_tool",
            arguments={"message": "test"},
            context=context,
        )

        assert result.status == ToolStatus.SUCCESS
        mock_collector.record_tool_execution.assert_called_once()

        call_args = mock_collector.record_tool_execution.call_args
        assert call_args.kwargs["tool_name"] == "fast_tool"
        assert call_args.kwargs["status"] == "success"
        assert call_args.kwargs["execution_time_ms"] > 0

    @pytest.mark.asyncio
    async def test_execute_timeout_with_metrics(self, registry, slow_tool, context):
        """Test that timeout metrics are recorded."""
        registry.register(slow_tool)

        mock_collector = MagicMock()
        executor = ToolExecutor(registry, mock_collector)

        result = await executor.execute(
            tool_name="slow_tool",
            arguments={},
            context=context,
        )

        assert result.status == ToolStatus.TIMEOUT
        mock_collector.record_tool_execution.assert_called_once()

        call_args = mock_collector.record_tool_execution.call_args
        assert call_args.kwargs["status"] == "timeout"


class TestToolContext:
    """Tests for ToolContext class."""

    def test_context_creation(self):
        """Test context creation with required fields."""
        context = ToolContext(
            call_id="call-123",
            session_id="session-456",
            turn_number=5,
        )

        assert context.call_id == "call-123"
        assert context.session_id == "session-456"
        assert context.turn_number == 5
        assert not context.cancelled

    def test_context_cancel(self):
        """Test cancellation support."""
        context = ToolContext(
            call_id="call-123",
            session_id="session-456",
            turn_number=1,
        )

        assert not context.is_cancelled()

        context.cancel()

        assert context.is_cancelled()
        assert context.cancelled

    def test_get_last_user_message(self):
        """Test getting last user message from history."""
        context = ToolContext(
            call_id="call-123",
            session_id="session-456",
            turn_number=1,
            conversation_history=[
                {"role": "user", "content": "First message"},
                {"role": "assistant", "content": "Response"},
                {"role": "user", "content": "Second message"},
            ],
        )

        assert context.get_last_user_message() == "Second message"

    def test_get_last_user_message_empty_history(self):
        """Test getting last user message with empty history."""
        context = ToolContext(
            call_id="call-123",
            session_id="session-456",
            turn_number=1,
        )

        assert context.get_last_user_message() is None


class TestToolResult:
    """Tests for ToolResult class."""

    def test_success_result(self):
        """Test successful result creation."""
        result = success_result({"key": "value"})

        assert result.status == ToolStatus.SUCCESS
        assert result.content == {"key": "value"}
        assert result.is_success()

    def test_error_result(self):
        """Test error result creation."""
        result = error_result("Item not found", error_code="NOT_FOUND")

        assert result.status == ToolStatus.ERROR
        assert result.error_code == "NOT_FOUND"
        assert result.error_message == "Item not found"
        assert not result.is_success()

    def test_to_bedrock_tool_result_success(self):
        """Test Bedrock format for successful result."""
        result = success_result({"data": "value"})

        bedrock_result = result.to_bedrock_tool_result("tool-123")

        assert "toolResult" in bedrock_result
        assert bedrock_result["toolResult"]["toolUseId"] == "tool-123"
        assert bedrock_result["toolResult"]["status"] == "success"
        assert bedrock_result["toolResult"]["content"][0]["json"] == {"data": "value"}

    def test_to_bedrock_tool_result_error(self):
        """Test Bedrock format for error result."""
        result = error_result("ERROR_CODE", "Error message")

        bedrock_result = result.to_bedrock_tool_result("tool-456")

        assert "toolResult" in bedrock_result
        assert bedrock_result["toolResult"]["toolUseId"] == "tool-456"
        assert bedrock_result["toolResult"]["status"] == "error"
        assert "ERROR_CODE" in bedrock_result["toolResult"]["content"][0]["text"]

    def test_to_user_message_success(self):
        """Test user message for success is empty."""
        result = success_result({})
        assert result.to_user_message() == ""

    def test_to_user_message_timeout(self):
        """Test user message for timeout."""
        result = ToolResult(status=ToolStatus.TIMEOUT)
        message = result.to_user_message()
        assert "longer than expected" in message

    def test_to_user_message_error(self):
        """Test user message for error."""
        result = error_result("ERROR", "Details")
        message = result.to_user_message()
        assert "encountered" in message

    def test_to_dict(self):
        """Test serialization to dict."""
        result = success_result({"key": "value"})
        result.execution_time_ms = 123.456

        data = result.to_dict()

        assert data["status"] == "success"
        assert data["content"] == {"key": "value"}
        assert data["execution_time_ms"] == 123.5  # Rounded

    def test_run_llm_default_is_none(self):
        """Test that run_llm defaults to None (Pipecat decides)."""
        result = success_result({"key": "value"})
        assert result.run_llm is None

    def test_run_llm_false(self):
        """Test that run_llm can be set to False to suppress re-inference."""
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            content={"done": True},
            run_llm=False,
        )
        assert result.run_llm is False

    def test_run_llm_included_in_to_dict_when_set(self):
        """Test that run_llm appears in to_dict when explicitly set."""
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            content={"done": True},
            run_llm=False,
        )
        data = result.to_dict()
        assert data["run_llm"] is False

    def test_run_llm_excluded_from_to_dict_when_none(self):
        """Test that run_llm is omitted from to_dict when None (default)."""
        result = success_result({"key": "value"})
        data = result.to_dict()
        assert "run_llm" not in data
