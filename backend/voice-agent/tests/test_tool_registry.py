"""Tests for the tool registry module."""

import pytest

try:
    from app.tools import (
        ToolCategory,
        ToolDefinition,
        ToolParameter,
        ToolRegistry,
        ToolRegistryError,
        ToolResult,
        ToolStatus,
        get_global_registry,
        reset_global_registry,
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
def registry():
    """Create a fresh tool registry for each test."""
    return ToolRegistry()


@pytest.fixture
def sample_tool():
    """Create a sample tool definition."""

    async def sample_executor(args, context):
        return success_result({"echo": args.get("message", "")})

    return ToolDefinition(
        name="sample_tool",
        description="A sample tool for testing",
        category=ToolCategory.TESTING,
        parameters=[
            ToolParameter(
                name="message",
                type="string",
                description="Message to echo",
                required=True,
            ),
        ],
        executor=sample_executor,
        timeout_seconds=5.0,
    )


@pytest.fixture
def minimal_tool():
    """Create a minimal tool with no parameters."""

    async def minimal_executor(args, context):
        return success_result({"status": "ok"})

    return ToolDefinition(
        name="minimal_tool",
        description="A minimal tool",
        category=ToolCategory.SYSTEM,
        parameters=[],
        executor=minimal_executor,
    )


# =============================================================================
# ToolRegistry Tests
# =============================================================================


class TestToolRegistry:
    """Tests for ToolRegistry class."""

    def test_register_tool(self, registry, sample_tool):
        """Test basic tool registration."""
        registry.register(sample_tool)

        assert sample_tool.name in registry
        assert len(registry) == 1
        assert registry.get(sample_tool.name) == sample_tool

    def test_register_multiple_tools(self, registry, sample_tool, minimal_tool):
        """Test registering multiple tools."""
        registry.register(sample_tool)
        registry.register(minimal_tool)

        assert len(registry) == 2
        assert sample_tool.name in registry
        assert minimal_tool.name in registry

    def test_register_duplicate_raises_error(self, registry, sample_tool):
        """Test that registering duplicate tool name raises error."""
        registry.register(sample_tool)

        with pytest.raises(ToolRegistryError, match="already registered"):
            registry.register(sample_tool)

    def test_register_after_lock_raises_error(
        self, registry, sample_tool, minimal_tool
    ):
        """Test that registration fails after locking."""
        registry.register(sample_tool)
        registry.lock()

        with pytest.raises(ToolRegistryError, match="locked"):
            registry.register(minimal_tool)

    def test_get_nonexistent_tool_returns_none(self, registry):
        """Test that getting nonexistent tool returns None."""
        assert registry.get("nonexistent") is None

    def test_get_all_definitions(self, registry, sample_tool, minimal_tool):
        """Test getting all tool definitions."""
        registry.register(sample_tool)
        registry.register(minimal_tool)

        definitions = registry.get_all_definitions()
        assert len(definitions) == 2
        assert sample_tool in definitions
        assert minimal_tool in definitions

    def test_get_tool_names(self, registry, sample_tool, minimal_tool):
        """Test getting all tool names."""
        registry.register(sample_tool)
        registry.register(minimal_tool)

        names = registry.get_tool_names()
        assert len(names) == 2
        assert "sample_tool" in names
        assert "minimal_tool" in names

    def test_is_locked(self, registry, sample_tool):
        """Test is_locked property."""
        assert not registry.is_locked()

        registry.register(sample_tool)
        registry.lock()

        assert registry.is_locked()

    def test_contains_operator(self, registry, sample_tool):
        """Test __contains__ operator."""
        assert sample_tool.name not in registry

        registry.register(sample_tool)

        assert sample_tool.name in registry

    def test_len_operator(self, registry, sample_tool, minimal_tool):
        """Test __len__ operator."""
        assert len(registry) == 0

        registry.register(sample_tool)
        assert len(registry) == 1

        registry.register(minimal_tool)
        assert len(registry) == 2


class TestToolRegistryValidation:
    """Tests for tool definition validation."""

    def test_empty_name_raises_error(self, registry):
        """Test that empty tool name raises error."""

        async def executor(args, context):
            return success_result({})

        tool = ToolDefinition(
            name="",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[],
            executor=executor,
        )

        with pytest.raises(ValueError, match="name is required"):
            registry.register(tool)

    def test_invalid_name_characters_raises_error(self, registry):
        """Test that tool name with special characters raises error."""

        async def executor(args, context):
            return success_result({})

        tool = ToolDefinition(
            name="invalid-name!",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[],
            executor=executor,
        )

        with pytest.raises(ValueError, match="alphanumeric"):
            registry.register(tool)

    def test_empty_description_raises_error(self, registry):
        """Test that empty description raises error."""

        async def executor(args, context):
            return success_result({})

        tool = ToolDefinition(
            name="test_tool",
            description="",
            category=ToolCategory.TESTING,
            parameters=[],
            executor=executor,
        )

        with pytest.raises(ValueError, match="requires a description"):
            registry.register(tool)

    def test_non_callable_executor_raises_error(self, registry):
        """Test that non-callable executor raises error."""
        tool = ToolDefinition(
            name="test_tool",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[],
            executor="not_callable",  # type: ignore
        )

        with pytest.raises(ValueError, match="must be callable"):
            registry.register(tool)

    def test_invalid_timeout_raises_error(self, registry):
        """Test that invalid timeout raises error."""

        async def executor(args, context):
            return success_result({})

        tool = ToolDefinition(
            name="test_tool",
            description="Test",
            category=ToolCategory.TESTING,
            parameters=[],
            executor=executor,
            timeout_seconds=-1,
        )

        with pytest.raises(ValueError, match="timeout must be positive"):
            registry.register(tool)


class TestBedrockToolConfig:
    """Tests for Bedrock toolConfig generation."""

    def test_get_bedrock_tool_config_empty(self, registry):
        """Test empty registry returns empty tools list."""
        config = registry.get_bedrock_tool_config()
        assert config == {"tools": []}

    def test_get_bedrock_tool_config_single_tool(self, registry, sample_tool):
        """Test Bedrock config for single tool."""
        registry.register(sample_tool)
        config = registry.get_bedrock_tool_config()

        assert "tools" in config
        assert len(config["tools"]) == 1

        tool_spec = config["tools"][0]
        assert "toolSpec" in tool_spec
        assert tool_spec["toolSpec"]["name"] == "sample_tool"
        assert "description" in tool_spec["toolSpec"]
        assert "inputSchema" in tool_spec["toolSpec"]

    def test_bedrock_input_schema_format(self, registry, sample_tool):
        """Test that input schema has correct JSON Schema format."""
        registry.register(sample_tool)
        config = registry.get_bedrock_tool_config()

        input_schema = config["tools"][0]["toolSpec"]["inputSchema"]["json"]
        assert input_schema["type"] == "object"
        assert "properties" in input_schema
        assert "message" in input_schema["properties"]
        assert input_schema["properties"]["message"]["type"] == "string"
        assert "required" in input_schema
        assert "message" in input_schema["required"]


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_get_global_registry(self):
        """Test getting global registry returns same instance."""
        reset_global_registry()

        registry1 = get_global_registry()
        registry2 = get_global_registry()

        assert registry1 is registry2

    def test_reset_global_registry(self):
        """Test resetting global registry creates new instance."""
        registry1 = get_global_registry()
        reset_global_registry()
        registry2 = get_global_registry()

        assert registry1 is not registry2
