"""Tests for the tool schema module."""

import pytest

try:
    from app.tools import (
        ToolCategory,
        ToolDefinition,
        ToolParameter,
        success_result,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_executor():
    """Create a sample executor function."""

    async def executor(args, context):
        return success_result({})

    return executor


# =============================================================================
# ToolParameter Tests
# =============================================================================


class TestToolParameter:
    """Tests for ToolParameter class."""

    def test_basic_string_parameter(self):
        """Test basic string parameter."""
        param = ToolParameter(
            name="message",
            type="string",
            description="A message",
        )

        assert param.name == "message"
        assert param.type == "string"
        assert param.description == "A message"
        assert not param.required

    def test_required_parameter(self):
        """Test required parameter."""
        param = ToolParameter(
            name="id",
            type="string",
            description="Required ID",
            required=True,
        )

        assert param.required

    def test_enum_parameter(self):
        """Test parameter with enum constraint."""
        param = ToolParameter(
            name="color",
            type="string",
            description="Color choice",
            enum=["red", "green", "blue"],
        )

        assert param.enum == ["red", "green", "blue"]

    def test_pattern_parameter(self):
        """Test parameter with regex pattern."""
        param = ToolParameter(
            name="phone",
            type="string",
            description="Phone number",
            pattern=r"^\+[1-9]\d{1,14}$",
        )

        assert param.pattern == r"^\+[1-9]\d{1,14}$"

    def test_numeric_constraints(self):
        """Test parameter with numeric constraints."""
        param = ToolParameter(
            name="count",
            type="number",
            description="Count value",
            minimum=0,
            maximum=100,
        )

        assert param.minimum == 0
        assert param.maximum == 100

    def test_to_json_schema_basic(self):
        """Test JSON Schema generation for basic parameter."""
        param = ToolParameter(
            name="message",
            type="string",
            description="A message",
        )

        schema = param.to_json_schema()

        assert schema["type"] == "string"
        assert schema["description"] == "A message"

    def test_to_json_schema_with_enum(self):
        """Test JSON Schema generation with enum."""
        param = ToolParameter(
            name="status",
            type="string",
            description="Status",
            enum=["pending", "active", "complete"],
        )

        schema = param.to_json_schema()

        assert schema["enum"] == ["pending", "active", "complete"]

    def test_to_json_schema_with_constraints(self):
        """Test JSON Schema generation with all constraints."""
        param = ToolParameter(
            name="score",
            type="number",
            description="Score",
            minimum=0,
            maximum=100,
        )

        schema = param.to_json_schema()

        assert schema["minimum"] == 0
        assert schema["maximum"] == 100


# =============================================================================
# ToolDefinition Tests
# =============================================================================


class TestToolDefinition:
    """Tests for ToolDefinition class."""

    def test_basic_tool_definition(self, sample_executor):
        """Test basic tool definition."""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            category=ToolCategory.TESTING,
            parameters=[],
            executor=sample_executor,
        )

        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.category == ToolCategory.TESTING
        assert tool.timeout_seconds == 10.0  # Default

    def test_tool_with_parameters(self, sample_executor):
        """Test tool with parameters."""
        tool = ToolDefinition(
            name="param_tool",
            description="Tool with params",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="input",
                    type="string",
                    description="Input value",
                    required=True,
                ),
                ToolParameter(
                    name="count",
                    type="number",
                    description="Count",
                    required=False,
                ),
            ],
            executor=sample_executor,
        )

        assert len(tool.parameters) == 2

    def test_tool_with_custom_timeout(self, sample_executor):
        """Test tool with custom timeout."""
        tool = ToolDefinition(
            name="slow_tool",
            description="Slow tool",
            category=ToolCategory.TESTING,
            parameters=[],
            executor=sample_executor,
            timeout_seconds=30.0,
        )

        assert tool.timeout_seconds == 30.0

    def test_to_bedrock_tool_spec_no_params(self, sample_executor):
        """Test Bedrock spec for tool with no parameters."""
        tool = ToolDefinition(
            name="simple_tool",
            description="Simple tool description",
            category=ToolCategory.SYSTEM,
            parameters=[],
            executor=sample_executor,
        )

        spec = tool.to_bedrock_tool_spec()

        assert "toolSpec" in spec
        assert spec["toolSpec"]["name"] == "simple_tool"
        assert spec["toolSpec"]["description"] == "Simple tool description"
        assert "inputSchema" in spec["toolSpec"]
        assert spec["toolSpec"]["inputSchema"]["json"]["type"] == "object"
        assert spec["toolSpec"]["inputSchema"]["json"]["properties"] == {}

    def test_to_bedrock_tool_spec_with_params(self, sample_executor):
        """Test Bedrock spec for tool with parameters."""
        tool = ToolDefinition(
            name="complex_tool",
            description="Complex tool",
            category=ToolCategory.CUSTOMER_INFO,
            parameters=[
                ToolParameter(
                    name="customer_id",
                    type="string",
                    description="Customer ID",
                    required=True,
                ),
                ToolParameter(
                    name="include_orders",
                    type="boolean",
                    description="Include orders",
                    required=False,
                ),
            ],
            executor=sample_executor,
        )

        spec = tool.to_bedrock_tool_spec()
        input_schema = spec["toolSpec"]["inputSchema"]["json"]

        assert "customer_id" in input_schema["properties"]
        assert "include_orders" in input_schema["properties"]
        assert input_schema["properties"]["customer_id"]["type"] == "string"
        assert input_schema["properties"]["include_orders"]["type"] == "boolean"
        assert input_schema["required"] == ["customer_id"]

    def test_get_input_schema(self, sample_executor):
        """Test getting just the input schema."""
        tool = ToolDefinition(
            name="test",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="value",
                    type="string",
                    description="Value",
                    required=True,
                ),
            ],
            executor=sample_executor,
        )

        schema = tool.get_input_schema()

        assert schema["type"] == "object"
        assert "value" in schema["properties"]
        assert "required" in schema


class TestToolDefinitionValidation:
    """Tests for ToolDefinition argument validation."""

    def test_validate_arguments_valid(self, sample_executor):
        """Test validation with valid arguments."""
        tool = ToolDefinition(
            name="test",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="message",
                    type="string",
                    description="Message",
                    required=True,
                ),
            ],
            executor=sample_executor,
        )

        errors = tool.validate_arguments({"message": "hello"})
        assert errors == []

    def test_validate_arguments_missing_required(self, sample_executor):
        """Test validation with missing required parameter."""
        tool = ToolDefinition(
            name="test",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="required_field",
                    type="string",
                    description="Required",
                    required=True,
                ),
            ],
            executor=sample_executor,
        )

        errors = tool.validate_arguments({})
        assert len(errors) == 1
        assert "required_field" in errors[0]

    def test_validate_arguments_unknown_param(self, sample_executor):
        """Test validation with unknown parameter."""
        tool = ToolDefinition(
            name="test",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="known",
                    type="string",
                    description="Known",
                    required=False,
                ),
            ],
            executor=sample_executor,
        )

        errors = tool.validate_arguments({"unknown": "value"})
        assert len(errors) == 1
        assert "Unknown" in errors[0]

    def test_validate_arguments_wrong_type(self, sample_executor):
        """Test validation with wrong type."""
        tool = ToolDefinition(
            name="test",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="count",
                    type="number",
                    description="Count",
                    required=False,
                ),
            ],
            executor=sample_executor,
        )

        errors = tool.validate_arguments({"count": "not a number"})
        assert len(errors) == 1
        assert "expected type" in errors[0]

    def test_validate_arguments_enum_violation(self, sample_executor):
        """Test validation with enum violation."""
        tool = ToolDefinition(
            name="test",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[
                ToolParameter(
                    name="color",
                    type="string",
                    description="Color",
                    enum=["red", "green", "blue"],
                ),
            ],
            executor=sample_executor,
        )

        errors = tool.validate_arguments({"color": "yellow"})
        assert len(errors) == 1
        assert "must be one of" in errors[0]


class TestToolCategory:
    """Tests for ToolCategory enum."""

    def test_all_categories_exist(self):
        """Test that all expected categories exist."""
        assert ToolCategory.CUSTOMER_INFO.value == "customer_info"
        assert ToolCategory.ORDER_MANAGEMENT.value == "order_management"
        assert ToolCategory.CRM.value == "crm"
        assert ToolCategory.KNOWLEDGE_BASE.value == "knowledge_base"
        assert ToolCategory.SYSTEM.value == "system"
        assert ToolCategory.TESTING.value == "testing"
