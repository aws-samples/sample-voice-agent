"""Tool definition schemas for the tool calling framework.

This module provides the core data structures for defining tools that can be
invoked by the LLM during voice conversations.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from .capabilities import PipelineCapability
    from .context import ToolContext
    from .result import ToolResult


class ToolCategory(Enum):
    """Tool categories for organization and metrics."""

    CUSTOMER_INFO = "customer_info"
    ORDER_MANAGEMENT = "order_management"
    CRM = "crm"
    CUSTOMER_SERVICE = "customer_service"
    AUTHENTICATION = "authentication"
    KNOWLEDGE_BASE = "knowledge_base"
    SYSTEM = "system"
    TESTING = "testing"


@dataclass
class ToolParameter:
    """JSON Schema parameter definition for a tool.

    Attributes:
        name: Parameter name (used as key in arguments dict)
        type: JSON Schema type ("string", "number", "boolean", "array", "object")
        description: Human-readable description for the LLM
        required: Whether this parameter must be provided
        enum: List of allowed values (for string type)
        pattern: Regex pattern for validation (for string type)
        minimum: Minimum value (for number type)
        maximum: Maximum value (for number type)
    """

    name: str
    type: str
    description: str
    required: bool = False
    enum: Optional[List[str]] = None
    pattern: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema property format."""
        schema: Dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }

        if self.enum is not None:
            schema["enum"] = self.enum
        if self.pattern is not None:
            schema["pattern"] = self.pattern
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum

        return schema


# Type alias for tool executor function signature
ToolExecutorFunc = Callable[[Dict[str, Any], "ToolContext"], Awaitable["ToolResult"]]


@dataclass
class ToolDefinition:
    """Complete tool specification for registration.

    This maps to Bedrock Converse API toolConfig format and provides all
    metadata needed for tool registration, execution, and observability.

    Attributes:
        name: Unique tool identifier (alphanumeric + underscores)
        description: Human-readable description for the LLM to understand when to use
        category: Tool category for organization and metrics
        parameters: List of parameter definitions
        executor: Async function that executes the tool
        timeout_seconds: Maximum execution time before timeout
        allow_during_barge_in: If False, cancel execution when user interrupts
        version: Tool version string
        requires_auth: Whether tool requires authenticated session
        requires: Pipeline capabilities this tool needs to function.
            The tool is only registered if all required capabilities are
            available. An empty frozenset means no special requirements
            (equivalent to requiring only BASIC).

    Example:
        >>> from app.tools.capabilities import PipelineCapability
        >>> tool = ToolDefinition(
        ...     name="get_current_time",
        ...     description="Get the current date and time",
        ...     category=ToolCategory.SYSTEM,
        ...     parameters=[],
        ...     executor=get_time_executor,
        ...     timeout_seconds=2.0,
        ...     requires=frozenset({PipelineCapability.BASIC}),
        ... )
    """

    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter]
    executor: ToolExecutorFunc
    timeout_seconds: float = 10.0
    allow_during_barge_in: bool = False
    version: str = "1.0.0"
    requires_auth: bool = False
    requires: FrozenSet["PipelineCapability"] = field(default_factory=frozenset)

    def _build_properties_and_required(
        self,
    ) -> tuple[Dict[str, Any], List[str]]:
        """Build JSON Schema properties and required list from parameters."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return properties, required

    def to_bedrock_tool_spec(self) -> Dict[str, Any]:
        """Convert to Bedrock Converse API toolSpec format.

        Returns:
            Dict in Bedrock toolSpec format:
            {
              "toolSpec": {
                "name": "tool_name",
                "description": "...",
                "inputSchema": {
                  "json": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                  }
                }
              }
            }
        """
        properties, required = self._build_properties_and_required()

        input_schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }

        if required:
            input_schema["required"] = required

        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {"json": input_schema},
            }
        }

    def to_function_schema(self) -> Any:
        """Convert to pipecat FunctionSchema for use with LLMContext/ToolsSchema.

        Returns:
            FunctionSchema instance compatible with pipecat's ToolsSchema.
        """
        from pipecat.adapters.schemas.function_schema import FunctionSchema

        properties, required = self._build_properties_and_required()

        return FunctionSchema(
            name=self.name,
            description=self.description,
            properties=properties,
            required=required,
        )

    def get_input_schema(self) -> Dict[str, Any]:
        """Get just the input schema for Pipecat registration.

        Returns:
            JSON Schema dict for the tool's parameters.
        """
        return self.to_bedrock_tool_spec()["toolSpec"]["inputSchema"]["json"]

    def validate_arguments(self, arguments: Dict[str, Any]) -> List[str]:
        """Validate arguments against parameter definitions.

        Args:
            arguments: Dict of argument name to value

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []

        # Check required parameters
        for param in self.parameters:
            if param.required and param.name not in arguments:
                errors.append(f"Missing required parameter: {param.name}")

        # Check for unknown parameters
        known_params = {p.name for p in self.parameters}
        for arg_name in arguments:
            if arg_name not in known_params:
                errors.append(f"Unknown parameter: {arg_name}")

        # Type validation (basic)
        for param in self.parameters:
            if param.name in arguments:
                value = arguments[param.name]
                if not self._check_type(value, param.type):
                    errors.append(
                        f"Parameter '{param.name}' expected type {param.type}, "
                        f"got {type(value).__name__}"
                    )

                # Enum validation
                if param.enum is not None and value not in param.enum:
                    errors.append(
                        f"Parameter '{param.name}' must be one of: {param.enum}"
                    )

        return errors

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected JSON Schema type."""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        if expected_type not in type_map:
            return True  # Unknown type, skip validation

        expected = type_map[expected_type]
        return isinstance(value, expected)  # type: ignore[arg-type]
