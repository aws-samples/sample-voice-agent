"""Unit tests for flow_config (dynamic agent discovery and FlowManager factory).

Tests the dynamic agent discovery, node factory registration, A2A function
creation, global function building, and config_service integration for the
enable_flow_agents flag.

Run with: .venv/bin/python -m pytest tests/test_flow_config.py -v
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

try:
    from pipecat_flows import FlowManager, NodeConfig

    from app.flows.flow_config import (
        _build_a2a_flow_functions,
        _create_a2a_flow_function,
        _discover_agent_nodes,
        _register_all_node_factories,
        create_initial_node,
    )
    from app.flows.transitions import (
        get_available_targets,
        clear_node_factories,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (pipecat-flows)",
        allow_module_level=True,
    )


# =============================================================================
# Helpers
# =============================================================================


def _make_skill_info(skill_id: str, description: str, agent_name: str = "TestAgent"):
    """Create a mock AgentSkillInfo."""
    skill = MagicMock()
    skill.skill_id = skill_id
    skill.skill_name = skill_id.replace("_", " ").title()
    skill.description = description
    skill.agent_name = agent_name
    skill.agent_url = f"http://localhost:8080/{agent_name}"
    skill.tags = []
    return skill


def _make_agent_entry(
    name: str,
    description: str,
    service_name: str,
    skills: list,
    url: str = None,
):
    """Create a mock AgentEntry for registry tests."""
    entry = MagicMock()
    entry.agent_name = name
    entry.agent_description = description
    entry.skills = skills
    entry.agent = MagicMock()
    entry.agent.invoke_async = AsyncMock(return_value=MagicMock())

    endpoint = MagicMock()
    endpoint.name = service_name
    endpoint.url = url or f"http://localhost:8080/{service_name}"
    entry.endpoint = endpoint

    return entry


def _make_registry(agents: dict):
    """Create a mock AgentRegistry with the given agent_cache.

    Args:
        agents: Dict mapping url -> AgentEntry mock
    """
    registry = MagicMock()
    registry._agent_cache = agents
    registry.a2a_timeout = 30
    return registry


# =============================================================================
# _build_a2a_flow_functions Tests
# =============================================================================


class TestBuildA2AFlowFunctions:
    """Tests for building Pipecat Flows-compatible functions from agent skills."""

    def test_returns_empty_list_for_empty_skills(self):
        """Should return empty list when skill list is empty."""
        result = _build_a2a_flow_functions(
            skills=[],
            agent=MagicMock(),
            a2a_timeout=30.0,
        )
        assert result == []

    def test_creates_one_function_per_skill(self):
        """Should create a flow function for each skill."""
        skills = [
            _make_skill_info("search_knowledge_base", "Search the KB"),
            _make_skill_info("get_article", "Get a specific article"),
        ]

        result = _build_a2a_flow_functions(
            skills=skills,
            agent=MagicMock(),
            a2a_timeout=30.0,
        )
        assert len(result) == 2
        assert result[0].__name__ == "search_knowledge_base"
        assert result[1].__name__ == "get_article"

    def test_single_skill_creates_one_function(self):
        """Should handle single-skill agents correctly."""
        skills = [_make_skill_info("search_knowledge_base", "Search KB")]

        result = _build_a2a_flow_functions(
            skills=skills,
            agent=MagicMock(),
            a2a_timeout=15.0,
        )
        assert len(result) == 1
        assert result[0].__name__ == "search_knowledge_base"


# =============================================================================
# _create_a2a_flow_function Tests
# =============================================================================


class TestCreateA2AFlowFunction:
    """Tests for individual A2A flow function creation."""

    def test_function_has_correct_name(self):
        """Created function should have the skill ID as its name."""
        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=MagicMock(),
        )
        assert fn.__name__ == "search_knowledge_base"

    def test_function_has_docstring(self):
        """Created function should have a docstring from the description."""
        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search the knowledge base for information",
            agent=MagicMock(),
        )
        assert "Search the knowledge base" in fn.__doc__
        assert "query" in fn.__doc__

    def test_function_has_cancel_on_interruption_false(self):
        """A2A functions should set _flows_cancel_on_interruption=False to
        protect in-flight A2A calls from barge-in cancellation."""
        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=MagicMock(),
        )
        assert hasattr(fn, "_flows_cancel_on_interruption")
        assert fn._flows_cancel_on_interruption is False

    @pytest.mark.asyncio
    async def test_function_calls_agent(self):
        """Created function should call agent.invoke_async with the query."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.message = {"role": "assistant", "content": [{"text": "Answer"}]}
        mock_agent.invoke_async = AsyncMock(return_value=mock_result)

        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=mock_agent,
            timeout_seconds=10.0,
        )

        fm = MagicMock()
        result, node = await fn(fm, query="What is the return policy?")

        mock_agent.invoke_async.assert_called_once_with("What is the return policy?")
        assert node is None  # A2A calls don't trigger transitions
        assert "result" in result
        assert "Answer" in result["result"]

    @pytest.mark.asyncio
    async def test_function_handles_timeout(self):
        """Created function should handle timeout gracefully."""
        import asyncio

        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(side_effect=asyncio.TimeoutError())

        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=mock_agent,
            timeout_seconds=0.001,
        )

        fm = MagicMock()
        result, node = await fn(fm, query="test")

        assert result["error"] is True
        assert result["error_code"] == "A2A_TIMEOUT"
        assert node is None

    @pytest.mark.asyncio
    async def test_function_handles_error(self):
        """Created function should handle exceptions gracefully."""
        mock_agent = MagicMock()
        mock_agent.invoke_async = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )

        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=mock_agent,
        )

        fm = MagicMock()
        result, node = await fn(fm, query="test")

        assert result["error"] is True
        assert result["error_code"] == "A2A_ERROR"
        assert "Connection failed" in result["error_message"]
        assert node is None

    @pytest.mark.asyncio
    async def test_custom_category_passed_to_metrics(self):
        """Custom category should be used for metrics recording."""
        mock_agent = MagicMock()
        mock_result = MagicMock()
        mock_result.message = {"role": "assistant", "content": [{"text": "Answer"}]}
        mock_agent.invoke_async = AsyncMock(return_value=mock_result)

        mock_collector = MagicMock()

        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=mock_agent,
            timeout_seconds=10.0,
            collector=mock_collector,
            category="knowledge_base",
        )

        fm = MagicMock()
        await fn(fm, query="test")

        mock_collector.record_tool_execution.assert_called_once()
        call_kwargs = mock_collector.record_tool_execution.call_args
        assert call_kwargs[1]["category"] == "knowledge_base"
        assert call_kwargs[1]["status"] == "success"


# =============================================================================
# _discover_agent_nodes Tests
# =============================================================================


class TestDiscoverAgentNodes:
    """Tests for dynamic agent discovery from the registry."""

    def test_returns_empty_dict_when_no_registry(self):
        """Should return empty dict when registry is None."""
        result = _discover_agent_nodes(None)
        assert result == {}

    def test_discovers_single_agent(self):
        """Should discover a single agent with its skills."""
        skills = [_make_skill_info("search_knowledge_base", "Search KB", "KB Agent")]
        entry = _make_agent_entry(
            name="KB Agent",
            description="Searches enterprise knowledge base.",
            service_name="kb-agent",
            skills=skills,
        )
        registry = _make_registry({"http://localhost:8080/kb-agent": entry})

        result = _discover_agent_nodes(registry)

        assert "kb_agent" in result
        assert result["kb_agent"]["agent_name"] == "KB Agent"
        assert (
            result["kb_agent"]["agent_description"]
            == "Searches enterprise knowledge base."
        )
        assert result["kb_agent"]["skill_ids"] == ["search_knowledge_base"]
        assert len(result["kb_agent"]["a2a_functions"]) == 1

    def test_discovers_multiple_agents(self):
        """Should discover multiple agents from the registry."""
        kb_skills = [_make_skill_info("search_kb", "Search KB")]
        kb_entry = _make_agent_entry(
            name="KB Agent",
            description="Knowledge base search.",
            service_name="kb-agent",
            skills=kb_skills,
        )

        crm_skills = [
            _make_skill_info("lookup_customer", "Lookup customer"),
            _make_skill_info("create_ticket", "Create support ticket"),
        ]
        crm_entry = _make_agent_entry(
            name="CRM Agent",
            description="Customer relationship management.",
            service_name="crm-agent",
            skills=crm_skills,
        )

        registry = _make_registry(
            {
                "http://localhost:8080/kb-agent": kb_entry,
                "http://localhost:8080/crm-agent": crm_entry,
            }
        )

        result = _discover_agent_nodes(registry)

        assert len(result) == 2
        assert "kb_agent" in result
        assert "crm_agent" in result
        assert len(result["crm_agent"]["a2a_functions"]) == 2
        assert result["crm_agent"]["skill_ids"] == ["lookup_customer", "create_ticket"]

    def test_slugifies_service_names(self):
        """Node names should be slugified from CloudMap service names."""
        skills = [_make_skill_info("search", "Search")]
        entry = _make_agent_entry(
            name="Knowledge Base Agent",
            description="KB search.",
            service_name="knowledge-base-agent",
            skills=skills,
        )
        registry = _make_registry({"http://localhost/kba": entry})

        result = _discover_agent_nodes(registry)

        assert "knowledge_base_agent" in result

    def test_empty_registry_returns_empty(self):
        """Empty agent cache should return empty dict."""
        registry = _make_registry({})
        result = _discover_agent_nodes(registry)
        assert result == {}


# =============================================================================
# _register_all_node_factories Tests
# =============================================================================


class TestRegisterAllNodeFactories:
    """Tests for dynamic node factory registration."""

    @pytest.fixture(autouse=True)
    def clean_factories(self):
        """Clear node factories before and after each test."""
        clear_node_factories()
        yield
        clear_node_factories()

    def test_registers_orchestrator_by_default(self):
        """Should always register orchestrator and reception factories."""
        _register_all_node_factories(agent_nodes={})

        targets = get_available_targets()
        assert "orchestrator" in targets
        assert "reception" in targets

    def test_registers_specialist_nodes(self):
        """Should register one factory per discovered agent."""
        agent_nodes = {
            "kb_agent": {
                "agent_name": "KB Agent",
                "agent_description": "KB search.",
                "a2a_functions": [MagicMock()],
                "skill_ids": ["search_kb"],
            },
            "crm_agent": {
                "agent_name": "CRM Agent",
                "agent_description": "Customer management.",
                "a2a_functions": [MagicMock(), MagicMock()],
                "skill_ids": ["lookup_customer", "create_ticket"],
            },
        }

        _register_all_node_factories(agent_nodes)

        targets = get_available_targets()
        assert "kb_agent" in targets
        assert "crm_agent" in targets
        assert "orchestrator" in targets
        assert "reception" in targets

    def test_factories_produce_valid_nodes(self):
        """Registered factories should produce valid NodeConfig dicts."""
        agent_nodes = {
            "kb_agent": {
                "agent_name": "KB Agent",
                "agent_description": "Searches enterprise knowledge base.",
                "a2a_functions": [],
                "skill_ids": [],
            },
        }

        _register_all_node_factories(agent_nodes)

        # Import the factory registry to invoke factories
        from app.flows.transitions import _node_factories

        # Orchestrator factory should work
        orch_node = _node_factories["orchestrator"]()
        assert orch_node["name"] == "orchestrator"

        # Specialist factory should work
        kb_node = _node_factories["kb_agent"]()
        assert kb_node["name"] == "kb_agent"

    def test_clears_stale_registrations(self):
        """Should clear old factories before re-registering."""
        from app.flows.transitions import register_node_factory

        # Register a stale factory
        register_node_factory("stale_agent", lambda: {})

        # Now register fresh set
        _register_all_node_factories(agent_nodes={})

        targets = get_available_targets()
        assert "stale_agent" not in targets
        assert "orchestrator" in targets

    def test_orchestrator_factory_receives_agent_descriptions(self):
        """Orchestrator factory should build nodes with agent descriptions."""
        agent_nodes = {
            "kb_agent": {
                "agent_name": "KB Agent",
                "agent_description": "Searches KB for docs.",
                "a2a_functions": [],
                "skill_ids": [],
            },
        }
        descriptions = {"kb_agent": "Searches KB for docs."}

        _register_all_node_factories(agent_nodes, agent_descriptions=descriptions)

        from app.flows.transitions import _node_factories

        orch_node = _node_factories["orchestrator"]()
        task_content = orch_node["task_messages"][0]["content"]
        assert "kb_agent" in task_content


# =============================================================================
# create_initial_node Tests
# =============================================================================


class TestCreateInitialNode:
    """Tests for create_initial_node."""

    def test_returns_orchestrator_node(self):
        """Should return the orchestrator node."""
        node = create_initial_node()
        assert isinstance(node, dict)
        assert node["name"] == "orchestrator"

    def test_initial_node_is_first_entry(self):
        """Should be configured for first entry (greeting, not 'anything else')."""
        node = create_initial_node()
        # First entry should not have RESET_WITH_SUMMARY
        assert node.get("context_strategy") is None
        # Should have greeting pre-action
        tts_actions = [
            a for a in (node.get("pre_actions") or []) if a.get("type") == "tts_say"
        ]
        if tts_actions:
            assert "anything else" not in tts_actions[0]["text"].lower()

    def test_initial_node_with_registry(self):
        """Should include agent descriptions when registry is provided."""
        skills = [_make_skill_info("search_kb", "Search KB")]
        entry = _make_agent_entry(
            name="KB Agent",
            description="Searches knowledge base.",
            service_name="kb-agent",
            skills=skills,
        )
        registry = _make_registry({"http://localhost:8080/kb-agent": entry})

        node = create_initial_node(a2a_registry=registry)

        task_content = node["task_messages"][0]["content"]
        assert "kb_agent" in task_content
        assert "knowledge base" in task_content.lower()

    def test_initial_node_without_registry(self):
        """Should use fallback task when no registry provided."""
        node = create_initial_node(a2a_registry=None)
        task_content = node["task_messages"][0]["content"]
        assert "no specialist" in task_content.lower()


# =============================================================================
# Config Service Integration Tests
# =============================================================================


class TestConfigServiceIntegration:
    """Tests for the enable_flow_agents feature flag."""

    def test_feature_flags_has_enable_flow_agents(self):
        """FeatureFlags should have the enable_flow_agents field."""
        from app.services.config_service import FeatureFlags

        flags = FeatureFlags()
        assert hasattr(flags, "enable_flow_agents")
        assert flags.enable_flow_agents is False  # Default

    def test_app_config_has_flow_max_transitions(self):
        """AppConfig should have the flow_max_transitions field."""
        from app.services.config_service import AppConfig

        config = AppConfig()
        assert hasattr(config, "flow_max_transitions")
        assert config.flow_max_transitions == 10  # Default


# =============================================================================
# cancel_on_interruption Tests
# =============================================================================


class TestCancelOnInterruption:
    """Tests that flow functions set cancel_on_interruption=False.

    Pipecat Flows' FlowsDirectFunctionWrapper defaults cancel_on_interruption
    to True for backward compatibility. Our functions must explicitly set
    _flows_cancel_on_interruption=False to prevent barge-in from cancelling
    in-flight tool calls.
    """

    def test_a2a_flow_function_has_attribute(self):
        """A2A flow functions should set _flows_cancel_on_interruption=False."""
        fn = _create_a2a_flow_function(
            skill_id="search_knowledge_base",
            description="Search KB",
            agent=MagicMock(),
        )
        assert hasattr(fn, "_flows_cancel_on_interruption")
        assert fn._flows_cancel_on_interruption is False

    def test_a2a_flow_functions_batch_all_have_attribute(self):
        """All functions from _build_a2a_flow_functions should be protected."""
        skills = [
            _make_skill_info("search_kb", "Search KB"),
            _make_skill_info("get_article", "Get article"),
        ]
        fns = _build_a2a_flow_functions(
            skills=skills,
            agent=MagicMock(),
            a2a_timeout=30.0,
        )
        for fn in fns:
            assert hasattr(fn, "_flows_cancel_on_interruption"), (
                f"Function {fn.__name__} missing _flows_cancel_on_interruption"
            )
            assert fn._flows_cancel_on_interruption is False

    def test_local_tool_flow_function_has_attribute(self):
        """Local tool flow functions should set _flows_cancel_on_interruption=False."""
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = MagicMock()
        tool_def.name = "get_current_time"
        tool_def.description = "Get the current time"
        tool_def.parameters = []

        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        assert hasattr(fn, "_flows_cancel_on_interruption")
        assert fn._flows_cancel_on_interruption is False

    def test_transfer_function_has_attribute(self):
        """The transfer function should set _flows_cancel_on_interruption=False."""
        from app.flows.transitions import transfer

        assert hasattr(transfer, "_flows_cancel_on_interruption")
        assert transfer._flows_cancel_on_interruption is False

    def test_flows_wrapper_reads_attribute(self):
        """FlowsDirectFunctionWrapper should read our attribute correctly.

        This verifies end-to-end that the wrapper picks up our attribute
        instead of defaulting to True.
        """
        from pipecat_flows.types import FlowsDirectFunctionWrapper

        fn = _create_a2a_flow_function(
            skill_id="test_tool",
            description="Test tool for cancel_on_interruption",
            agent=MagicMock(),
        )
        wrapper = FlowsDirectFunctionWrapper(function=fn)
        assert wrapper.cancel_on_interruption is False

    def test_undecorated_function_defaults_to_true(self):
        """A function WITHOUT the attribute should default to True (baseline)."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper

        async def bare_function(flow_manager, query: str) -> tuple:
            """A bare function without protection.

            Args:
                query: Test query.
            """
            return {"status": "ok"}, None

        wrapper = FlowsDirectFunctionWrapper(function=bare_function)
        # Default behavior in Flows: cancel_on_interruption=True
        assert wrapper.cancel_on_interruption is True


# =============================================================================
# Local Tool Signature Tests (hangup_call kwargs fix)
# =============================================================================


class TestLocalToolSignature:
    """Tests that local tool flow functions expose correct parameter signatures.

    Pipecat Flows uses inspect.signature() to extract tool schemas for the LLM.
    If the wrapper uses **kwargs, Flows creates a required parameter literally
    named "kwargs" and the LLM calls e.g. hangup_call(kwargs={"reason": "..."})
    instead of hangup_call(reason="...").

    The fix sets __signature__ on the wrapper so inspect.signature() returns
    explicit named parameters matching the ToolDefinition.
    """

    def _make_tool_def(self, name, params):
        """Create a mock ToolDefinition with the given parameters."""
        tool_def = MagicMock()
        tool_def.name = name
        tool_def.description = f"Test tool: {name}"
        mock_params = []
        for p in params:
            mp = MagicMock()
            mp.name = p["name"]
            mp.type = p["type"]
            mp.description = p.get("description", "")
            mp.required = p.get("required", True)
            mock_params.append(mp)
        tool_def.parameters = mock_params
        return tool_def

    def test_signature_has_named_params_not_kwargs(self):
        """Wrapper should expose named params, not **kwargs, to inspect.signature()."""
        import inspect
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = self._make_tool_def(
            "hangup_call",
            [
                {"name": "reason", "type": "string", "required": True},
            ],
        )
        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())
        assert "kwargs" not in param_names, "**kwargs must not leak into signature"
        assert "reason" in param_names, "Named param 'reason' must be in signature"

    def test_required_param_has_no_default(self):
        """Required parameters should have no default (inspect.Parameter.empty)."""
        import inspect
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = self._make_tool_def(
            "hangup_call",
            [
                {"name": "reason", "type": "string", "required": True},
            ],
        )
        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        sig = inspect.signature(fn)
        assert sig.parameters["reason"].default is inspect.Parameter.empty

    def test_optional_param_has_default_none(self):
        """Optional parameters should have default=None."""
        import inspect
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = self._make_tool_def(
            "get_current_time",
            [
                {"name": "timezone", "type": "string", "required": False},
            ],
        )
        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        sig = inspect.signature(fn)
        assert sig.parameters["timezone"].default is None

    def test_flows_wrapper_extracts_correct_schema(self):
        """FlowsDirectFunctionWrapper should see named params, not 'kwargs'."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = self._make_tool_def(
            "hangup_call",
            [
                {
                    "name": "reason",
                    "type": "string",
                    "description": "Why the call is ending",
                    "required": True,
                },
            ],
        )
        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        wrapper = FlowsDirectFunctionWrapper(function=fn)
        assert "reason" in wrapper.properties, "Wrapper must see 'reason' property"
        assert "kwargs" not in wrapper.properties, (
            "Wrapper must NOT see 'kwargs' property"
        )
        assert wrapper.properties["reason"].get("type") == "string"
        assert "reason" in wrapper.required

    def test_flows_schema_for_tool_with_multiple_params(self):
        """Tool with multiple params should produce correct schema."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = self._make_tool_def(
            "transfer_to_agent",
            [
                {
                    "name": "reason",
                    "type": "string",
                    "description": "Transfer reason",
                    "required": True,
                },
                {
                    "name": "department",
                    "type": "string",
                    "description": "Department",
                    "required": False,
                },
                {
                    "name": "priority",
                    "type": "string",
                    "description": "Priority level",
                    "required": False,
                },
            ],
        )
        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        wrapper = FlowsDirectFunctionWrapper(function=fn)
        assert set(wrapper.properties.keys()) == {"reason", "department", "priority"}
        assert wrapper.required == ["reason"]

    def test_flows_schema_for_no_param_tool(self):
        """Tool with no params should produce empty properties."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper
        from app.flows.flow_config import _create_local_tool_flow_function

        tool_def = self._make_tool_def("get_current_time", [])
        fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=MagicMock(),
            session_id="test-session",
            transport=MagicMock(),
        )
        wrapper = FlowsDirectFunctionWrapper(function=fn)
        assert wrapper.properties == {}
        assert wrapper.required == []


# =============================================================================
# Collector Wiring Tests (Phase 4.4)
# =============================================================================


class TestCollectorWiring:
    """Tests that create_flow_manager stores collector in flow_manager.state."""

    def _make_mock_flow_manager(self):
        """Create a mock FlowManager that behaves like the real one."""
        fm = MagicMock()
        fm.state = {}
        return fm

    @patch("app.flows.flow_config.InstrumentedFlowManager")
    @patch("app.flows.flow_config._build_global_functions", return_value=[])
    @patch("app.flows.flow_config._register_all_node_factories")
    @patch("app.flows.flow_config._discover_agent_nodes", return_value={})
    def test_collector_stored_in_state(
        self, mock_discover, mock_register, mock_global_fns, MockFlowManager
    ):
        """create_flow_manager should store collector in flow_manager.state."""
        from app.flows.flow_config import create_flow_manager
        from app.flows.transitions import _COLLECTOR_KEY

        mock_fm = self._make_mock_flow_manager()
        MockFlowManager.return_value = mock_fm

        collector = MagicMock()
        collector.set_agent_node = MagicMock()

        fm = create_flow_manager(
            task=MagicMock(),
            llm=MagicMock(),
            context_aggregator=MagicMock(),
            transport=MagicMock(),
            session_id="test-session",
            collector=collector,
        )

        assert fm.state.get(_COLLECTOR_KEY) is collector

    @patch("app.flows.flow_config.InstrumentedFlowManager")
    @patch("app.flows.flow_config._build_global_functions", return_value=[])
    @patch("app.flows.flow_config._register_all_node_factories")
    @patch("app.flows.flow_config._discover_agent_nodes", return_value={})
    def test_initial_agent_node_set_to_orchestrator(
        self, mock_discover, mock_register, mock_global_fns, MockFlowManager
    ):
        """create_flow_manager should set initial agent_node to 'orchestrator'."""
        from app.flows.flow_config import create_flow_manager

        mock_fm = self._make_mock_flow_manager()
        MockFlowManager.return_value = mock_fm

        collector = MagicMock()
        collector.set_agent_node = MagicMock()

        create_flow_manager(
            task=MagicMock(),
            llm=MagicMock(),
            context_aggregator=MagicMock(),
            transport=MagicMock(),
            session_id="test-session",
            collector=collector,
        )

        collector.set_agent_node.assert_called_once_with("orchestrator")

    @patch("app.flows.flow_config.InstrumentedFlowManager")
    @patch("app.flows.flow_config._build_global_functions", return_value=[])
    @patch("app.flows.flow_config._register_all_node_factories")
    @patch("app.flows.flow_config._discover_agent_nodes", return_value={})
    def test_no_collector_no_state_entry(
        self, mock_discover, mock_register, mock_global_fns, MockFlowManager
    ):
        """create_flow_manager without collector should not set _collector in state."""
        from app.flows.flow_config import create_flow_manager
        from app.flows.transitions import _COLLECTOR_KEY

        mock_fm = self._make_mock_flow_manager()
        MockFlowManager.return_value = mock_fm

        fm = create_flow_manager(
            task=MagicMock(),
            llm=MagicMock(),
            context_aggregator=MagicMock(),
            transport=MagicMock(),
            session_id="test-session",
            collector=None,
        )

        assert _COLLECTOR_KEY not in fm.state
