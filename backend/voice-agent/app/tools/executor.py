"""Tool executor for the tool calling framework.

This module provides the ToolExecutor class which handles async tool
execution with timeout handling, error recovery, and metrics collection.
"""

import asyncio
import time
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import structlog
from pipecat.services.llm_service import FunctionCallParams

from .context import ToolContext
from .registry import ToolRegistry
from .result import (
    ToolResult,
    ToolStatus,
    error_result,
    timeout_result,
)
from .result_summarizer import is_result_logging_enabled, summarize_tool_result

if TYPE_CHECKING:
    from ..observability import MetricsCollector

logger = structlog.get_logger(__name__)


class ToolExecutor:
    """Executes tools with timeout, error handling, and observability.

    Provides safe async execution of registered tools with configurable
    timeouts, structured error handling, and metrics collection.

    Usage:
        >>> registry = ToolRegistry()
        >>> registry.register(my_tool)
        >>>
        >>> executor = ToolExecutor(registry, metrics_collector)
        >>> result = await executor.execute(
        ...     tool_name="my_tool",
        ...     arguments={"param": "value"},
        ...     context=context,
        ... )
    """

    def __init__(
        self,
        registry: ToolRegistry,
        metrics_collector: Optional["MetricsCollector"] = None,
    ) -> None:
        """Initialize the tool executor.

        Args:
            registry: Tool registry containing tool definitions
            metrics_collector: Optional metrics collector for observability
        """
        self.registry = registry
        self.metrics_collector = metrics_collector

    async def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute a tool with timeout and error handling.

        Args:
            tool_name: Name of registered tool
            arguments: Tool arguments (validated against JSON schema)
            context: Execution context with session info

        Returns:
            ToolResult with status and content/error
        """
        start_time = time.perf_counter()

        # Get tool definition
        tool = self.registry.get(tool_name)
        if not tool:
            logger.error("tool_not_found", tool_name=tool_name)
            return error_result(
                error_code="TOOL_NOT_FOUND",
                error_message=f"Tool '{tool_name}' not found",
            )

        # Validate arguments
        validation_errors = tool.validate_arguments(arguments)
        if validation_errors:
            logger.warning(
                "tool_argument_validation_failed",
                tool_name=tool_name,
                errors=validation_errors,
            )
            return error_result(
                error_code="INVALID_ARGUMENTS",
                error_message="; ".join(validation_errors),
            )

        logger.info(
            "tool_execution_starting",
            tool_name=tool_name,
            call_id=context.call_id,
            turn_number=context.turn_number,
        )

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                tool.executor(arguments, context),
                timeout=tool.timeout_seconds,
            )

            execution_time_ms = (time.perf_counter() - start_time) * 1000
            result.execution_time_ms = execution_time_ms

            # Compute result summary when feature is enabled
            result_summary = None
            if result.is_success() and is_result_logging_enabled():
                try:
                    result_summary = summarize_tool_result(
                        result.content, tool_name=tool_name
                    )
                except Exception:
                    pass  # Never let summarization affect tool execution

            # Record metrics (includes result_summary in structured log)
            self._record_metrics(
                tool_name=tool_name,
                category=tool.category.value,
                status=result.status.value,
                execution_time_ms=execution_time_ms,
                result_summary=result_summary,
            )

            log_kwargs = {
                "tool_name": tool_name,
                "status": result.status.value,
                "execution_time_ms": round(execution_time_ms, 1),
                "call_id": context.call_id,
            }
            if result_summary is not None:
                log_kwargs["result_summary"] = result_summary

            logger.info("tool_execution_complete", **log_kwargs)

            if result_summary is not None and result.content is not None:
                logger.debug(
                    "tool_result_detail",
                    tool_name=tool_name,
                    call_id=context.call_id,
                    result_content=result.content,
                )

            return result

        except asyncio.TimeoutError:
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            logger.warning(
                "tool_execution_timeout",
                tool_name=tool_name,
                timeout_seconds=tool.timeout_seconds,
                call_id=context.call_id,
            )

            self._record_metrics(
                tool_name=tool_name,
                category=tool.category.value,
                status="timeout",
                execution_time_ms=execution_time_ms,
            )

            result = timeout_result(tool.timeout_seconds)
            result.execution_time_ms = execution_time_ms
            return result

        except asyncio.CancelledError:
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            logger.info(
                "tool_execution_cancelled",
                tool_name=tool_name,
                call_id=context.call_id,
            )

            self._record_metrics(
                tool_name=tool_name,
                category=tool.category.value,
                status="cancelled",
                execution_time_ms=execution_time_ms,
            )

            return ToolResult(
                status=ToolStatus.CANCELLED,
                execution_time_ms=execution_time_ms,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            logger.exception(
                "tool_execution_error",
                tool_name=tool_name,
                error=str(e),
                error_type=type(e).__name__,
                call_id=context.call_id,
            )

            self._record_metrics(
                tool_name=tool_name,
                category=tool.category.value,
                status="error",
                execution_time_ms=execution_time_ms,
            )

            result = error_result(
                error_code=type(e).__name__,
                error_message=str(e),
            )
            result.execution_time_ms = execution_time_ms
            return result

    def _record_metrics(
        self,
        tool_name: str,
        category: str,
        status: str,
        execution_time_ms: float,
        result_summary: Optional[str] = None,
    ) -> None:
        """Record tool execution metrics.

        Args:
            tool_name: Tool identifier
            category: Tool category
            status: Execution status
            execution_time_ms: Execution duration
            result_summary: Optional truncated summary of tool result
        """
        if self.metrics_collector is not None:
            try:
                self.metrics_collector.record_tool_execution(
                    tool_name=tool_name,
                    category=category,
                    status=status,
                    execution_time_ms=execution_time_ms,
                    result_summary=result_summary,
                )
            except Exception as e:
                # Don't let metrics failures affect tool execution
                logger.warning("failed_to_record_tool_metrics", error=str(e))


def create_pipecat_wrapper(
    tool_name: str,
    executor: ToolExecutor,
    context_factory: Callable[[], ToolContext],
):
    """Create a wrapper function for Pipecat's register_function.

    Pipecat expects a simple async function that takes arguments and returns
    a dict. This wrapper adapts our ToolExecutor to that interface.

    Args:
        tool_name: Name of the tool to wrap
        executor: ToolExecutor instance
        context_factory: Callable that returns a ToolContext for current session

    Returns:
        Async function compatible with Pipecat's register_function
    """

    async def wrapper(params: FunctionCallParams) -> None:
        """Pipecat function calling wrapper.

        This matches Pipecat's expected signature for registered functions.
        Accepts a single FunctionCallParams parameter.
        """
        # Create tool context from session state
        tool_context = context_factory()

        # Execute tool
        result = await executor.execute(
            tool_name=tool_name,
            arguments=dict(params.arguments),
            context=tool_context,
        )

        # Return result through Pipecat's callback
        if result.is_success():
            await params.result_callback(result.content)
        else:
            # For errors, return error info as content so LLM can respond appropriately
            await params.result_callback(
                {
                    "error": True,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                }
            )

    return wrapper
