"""Tool calling framework for the voice agent.

This module provides the infrastructure for registering and executing tools
that can be invoked by the LLM during voice conversations.

Usage:
    >>> from app.tools import (
    ...     ToolDefinition,
    ...     ToolParameter,
    ...     ToolCategory,
    ...     ToolContext,
    ...     ToolResult,
    ...     ToolStatus,
    ...     ToolRegistry,
    ...     ToolExecutor,
    ...     get_global_registry,
    ...     register_tool,
    ...     success_result,
    ...     error_result,
    ... )
    >>>
    >>> # Define a tool
    >>> async def my_executor(args: dict, context: ToolContext) -> ToolResult:
    ...     return success_result({"data": "value"})
    >>>
    >>> tool = ToolDefinition(
    ...     name="my_tool",
    ...     description="Does something useful",
    ...     category=ToolCategory.SYSTEM,
    ...     parameters=[
    ...         ToolParameter(name="input", type="string", description="Input value"),
    ...     ],
    ...     executor=my_executor,
    ... )
    >>>
    >>> # Register with global registry
    >>> register_tool(tool)
"""

from .schema import (
    ToolCategory,
    ToolDefinition,
    ToolParameter,
    ToolExecutorFunc,
)
from .capabilities import (
    PipelineCapability,
    detect_capabilities,
)
from .context import ToolContext
from .result import (
    ToolResult,
    ToolStatus,
    success_result,
    error_result,
    timeout_result,
    cancelled_result,
    direct_response_result,
)
from .registry import (
    ToolRegistry,
    ToolRegistryError,
    get_global_registry,
    reset_global_registry,
    register_tool,
)
from .executor import (
    ToolExecutor,
    create_pipecat_wrapper,
)

__all__ = [
    # Schema types
    "ToolCategory",
    "ToolDefinition",
    "ToolParameter",
    "ToolExecutorFunc",
    # Capabilities
    "PipelineCapability",
    "detect_capabilities",
    # Context
    "ToolContext",
    # Results
    "ToolResult",
    "ToolStatus",
    "success_result",
    "error_result",
    "timeout_result",
    "cancelled_result",
    "direct_response_result",
    # Registry
    "ToolRegistry",
    "ToolRegistryError",
    "get_global_registry",
    "reset_global_registry",
    "register_tool",
    # Executor
    "ToolExecutor",
    "create_pipecat_wrapper",
]
