"""Tool registry for the tool calling framework.

This module provides the ToolRegistry class for registering and managing
tool definitions, and converting them to Bedrock Converse API format.
"""

import structlog
from typing import Any, Dict, List, Optional

from .schema import ToolDefinition

logger = structlog.get_logger(__name__)


class ToolRegistryError(Exception):
    """Exception raised for tool registry errors."""

    pass


class ToolRegistry:
    """Central registry for available tools.

    Provides tool registration, validation, and lookup. Thread-safe for
    multi-session environments.

    Usage:
        >>> registry = ToolRegistry()
        >>> registry.register(get_customer_info_tool)
        >>> registry.register(check_order_status_tool)
        >>>
        >>> # Get all tools for LLM registration
        >>> tools = registry.get_all_definitions()
        >>>
        >>> # Get Bedrock format for API calls
        >>> tool_config = registry.get_bedrock_tool_config()
    """

    def __init__(self) -> None:
        """Initialize an empty tool registry."""
        self._tools: Dict[str, ToolDefinition] = {}
        self._locked: bool = False

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition.

        Args:
            tool: ToolDefinition to register

        Raises:
            ToolRegistryError: If tool name already registered or registry locked
            ValueError: If tool definition is invalid
        """
        if self._locked:
            raise ToolRegistryError(
                "Registry locked - no new tools can be registered after pipeline start"
            )

        if tool.name in self._tools:
            raise ToolRegistryError(f"Tool '{tool.name}' already registered")

        # Validate tool definition
        self._validate_tool(tool)

        self._tools[tool.name] = tool
        logger.info(
            "tool_registered",
            tool_name=tool.name,
            category=tool.category.value,
            timeout_seconds=tool.timeout_seconds,
        )

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get tool by name.

        Args:
            name: Tool name to look up

        Returns:
            ToolDefinition if found, None otherwise
        """
        return self._tools.get(name)

    def get_all_definitions(self) -> List[ToolDefinition]:
        """Get all registered tool definitions.

        Returns:
            List of all registered ToolDefinitions
        """
        return list(self._tools.values())

    def get_tool_names(self) -> List[str]:
        """Get names of all registered tools.

        Returns:
            List of tool names
        """
        return list(self._tools.keys())

    def get_bedrock_tool_config(self) -> Dict[str, Any]:
        """Get Bedrock Converse API toolConfig.

        Returns:
            Dict in Bedrock toolConfig format:
            {
              "tools": [
                {"toolSpec": {...}},
                {"toolSpec": {...}}
              ]
            }
        """
        return {"tools": [tool.to_bedrock_tool_spec() for tool in self._tools.values()]}

    def lock(self) -> None:
        """Lock registry to prevent further registrations.

        Should be called after all tools are registered and before
        the pipeline starts processing requests.
        """
        self._locked = True
        logger.info("tool_registry_locked", tool_count=len(self._tools))

    def is_locked(self) -> bool:
        """Check if registry is locked.

        Returns:
            True if no more tools can be registered
        """
        return self._locked

    def __len__(self) -> int:
        """Get number of registered tools."""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """Check if tool is registered by name."""
        return name in self._tools

    def _validate_tool(self, tool: ToolDefinition) -> None:
        """Validate tool definition.

        Args:
            tool: Tool definition to validate

        Raises:
            ValueError: If validation fails
        """
        if not tool.name:
            raise ValueError("Tool name is required")

        if not tool.name.replace("_", "").isalnum():
            raise ValueError(
                f"Tool name must be alphanumeric with underscores: {tool.name}"
            )

        if not tool.description:
            raise ValueError(f"Tool '{tool.name}' requires a description")

        if not callable(tool.executor):
            raise ValueError(f"Tool '{tool.name}' executor must be callable")

        if tool.timeout_seconds <= 0:
            raise ValueError(
                f"Tool '{tool.name}' timeout must be positive, got {tool.timeout_seconds}"
            )

        if tool.timeout_seconds > 30:
            logger.warning(
                "tool_long_timeout",
                tool_name=tool.name,
                timeout_seconds=tool.timeout_seconds,
                hint="consider reducing for voice UX",
            )


# Global registry instance
_global_registry: Optional[ToolRegistry] = None


def get_global_registry() -> ToolRegistry:
    """Get or create global tool registry.

    Returns:
        The global ToolRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """Reset the global registry (for testing).

    This clears all registered tools and creates a fresh registry.
    """
    global _global_registry
    _global_registry = ToolRegistry()


def register_tool(tool: ToolDefinition) -> None:
    """Register a tool with the global registry.

    Convenience function for registering tools without explicit
    registry access.

    Args:
        tool: ToolDefinition to register
    """
    get_global_registry().register(tool)
