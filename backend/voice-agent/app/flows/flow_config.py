"""FlowManager factory and dynamic node registration.

This module is the central orchestrator for the Pipecat Flows integration:
- Creates and configures the FlowManager
- Dynamically discovers A2A agents from the AgentRegistry
- Creates one specialist node per discovered agent (from Agent Card data)
- Registers node factories for the transition system
- Builds global functions from local voice pipeline tools

No hard-coded node definitions or tool mappings -- everything is derived
from Agent Card metadata at pipeline creation time. Deploying a new A2A
capability agent and registering it in CloudMap automatically creates a
new specialist node.

Usage from pipeline_ecs.py:
    from app.flows import create_flow_manager, create_initial_node

    flow_manager = create_flow_manager(task, llm, context_aggregator, transport, ...)
    initial_node = create_initial_node(a2a_registry)
    # Later, on first participant joined:
    await flow_manager.initialize(initial_node)
"""

from typing import Any, Callable, Dict, List, Optional

import structlog

import time as _time

from pipecat_flows import FlowManager

from .dependencies import (
    aggregate_agent_tags,
    mark_dependency_satisfied,
    SATISFIED_DEPS_KEY,
)
from .nodes.orchestrator import create_orchestrator_node
from .nodes.specialist import create_specialist_node, slugify_service_name
from .transitions import register_node_factory, clear_node_factories

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# InstrumentedFlowManager: subclass that times context summary generation
# ---------------------------------------------------------------------------


class InstrumentedFlowManager(FlowManager):
    """FlowManager subclass that instruments ``_update_llm_context``.

    The base ``_update_llm_context`` generates a conversation summary when
    ``ContextStrategy.RESET_WITH_SUMMARY`` is active, but the timing is
    internal to the library.  This override wraps the call to emit a
    ``ContextSummaryLatency`` CloudWatch metric and structured log event.

    The latency is emitted as a standalone EMF metric (separate from the
    ``agent_transition`` event) because the transition function returns
    *before* ``_set_node`` calls ``_update_llm_context``.
    """

    async def _update_llm_context(
        self, role_messages, task_messages, functions, strategy=None
    ):
        """Override to time summary generation and emit metrics."""
        from pipecat_flows import ContextStrategy

        needs_summary = (
            strategy is not None
            and getattr(strategy, "strategy", None)
            == ContextStrategy.RESET_WITH_SUMMARY
        )

        start = _time.monotonic()
        await super()._update_llm_context(
            role_messages, task_messages, functions, strategy
        )
        elapsed_ms = (_time.monotonic() - start) * 1000

        if needs_summary:
            collector = self.state.get("_collector")
            current_node = self._current_node or "unknown"

            logger.info(
                "context_summary_generated",
                summary_latency_ms=round(elapsed_ms, 1),
                target_node=current_node,
            )

            if collector:
                try:
                    # Update call-level summary latency aggregate
                    collector._call_metrics._summary_latencies_ms.append(elapsed_ms)
                    # Emit standalone EMF metric
                    collector._emf.emit_transition_metrics(
                        call_id=collector.call_id,
                        from_node="context_update",
                        to_node=current_node,
                        summary_latency_ms=elapsed_ms,
                    )
                except Exception:
                    pass


def _is_result_logging_enabled() -> bool:
    """Check if tool result logging is enabled (deferred import)."""
    try:
        from app.tools.result_summarizer import is_result_logging_enabled

        return is_result_logging_enabled()
    except Exception:
        return False


def _build_a2a_flow_functions(
    skills: List[Any],
    agent: Any,
    a2a_timeout: float,
    collector: Optional[Any] = None,
    category: str = "a2a",
) -> List[Any]:
    """Build Pipecat Flows-compatible functions for an agent's skills.

    Each A2A skill is wrapped in a direct function that takes a
    flow_manager and query parameter, routes to the A2A agent, and
    returns the result as a FlowResult.

    Skills with ``provides:<key>`` tags will mark the dependency as
    satisfied in flow_manager.state when the call succeeds.

    Args:
        skills: List of AgentSkillInfo from the agent's card
        agent: A2AAgent instance for this agent
        a2a_timeout: Timeout in seconds for A2A calls
        collector: Optional MetricsCollector for timing metrics
        category: Metrics category string for tools from this agent

    Returns:
        List of async direct functions for Pipecat Flows
    """
    from .dependencies import parse_skill_tags

    functions = []
    for skill in skills:
        provides_keys, _ = parse_skill_tags(skill.tags)

        flow_fn = _create_a2a_flow_function(
            skill_id=skill.skill_id,
            description=skill.description,
            agent=agent,
            timeout_seconds=a2a_timeout,
            collector=collector,
            provides_keys=provides_keys if provides_keys else None,
            category=category,
        )
        functions.append(flow_fn)

        logger.info(
            "flow_a2a_function_created",
            skill_id=skill.skill_id,
            agent=skill.agent_name,
            provides=sorted(provides_keys) if provides_keys else [],
        )

    return functions


def _create_a2a_flow_function(
    skill_id: str,
    description: str,
    agent: Any,
    timeout_seconds: float = 30.0,
    collector: Optional[Any] = None,
    provides_keys: Optional[set] = None,
    category: str = "a2a",
) -> Callable:
    """Create a Pipecat Flows direct function for an A2A skill.

    The returned function follows the Flows direct function convention:
    - First parameter is flow_manager (auto-injected by FlowManager)
    - Additional parameters are extracted from the function signature
    - Returns (FlowResult, None) since A2A calls don't trigger transitions

    The function name and docstring are used by Flows to generate the
    tool schema that the LLM sees.

    Args:
        skill_id: Unique skill identifier
        description: Tool description for the LLM
        agent: A2AAgent instance
        timeout_seconds: Timeout for A2A calls
        collector: Optional metrics collector
        provides_keys: Set of dependency keys this skill provides on success
        category: Metrics category string for this tool

    Returns:
        Async direct function for Pipecat Flows
    """
    import asyncio
    import time

    async def a2a_flow_function(flow_manager: Any, query: str) -> tuple:
        """Query placeholder."""
        start_time = time.monotonic()

        logger.info(
            "flow_a2a_call_start",
            skill_id=skill_id,
            query=query[:200],
        )

        try:
            result = await asyncio.wait_for(
                agent.invoke_async(query),
                timeout=timeout_seconds,
            )

            # Extract text from AgentResult
            from app.a2a.tool_adapter import extract_text_from_result

            response_text = extract_text_from_result(result)
            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Build log kwargs with optional result summary
            log_kwargs: dict = {
                "skill_id": skill_id,
                "elapsed_ms": round(elapsed_ms),
                "response_length": len(response_text),
            }

            result_summary = None
            if _is_result_logging_enabled():
                try:
                    from app.tools.result_summarizer import summarize_tool_result

                    result_summary = summarize_tool_result(
                        response_text, tool_name=skill_id
                    )
                except Exception:
                    pass

            if result_summary is not None:
                log_kwargs["result_summary"] = result_summary

            logger.info("flow_a2a_call_success", **log_kwargs)

            if result_summary is not None:
                logger.debug(
                    "flow_a2a_result_detail",
                    skill_id=skill_id,
                    result_content=response_text,
                )

            if collector:
                try:
                    collector.record_tool_execution(
                        tool_name=skill_id,
                        category=category,
                        status="success",
                        execution_time_ms=elapsed_ms,
                    )
                except Exception:
                    pass

            # Track provided dependencies in flow state
            if provides_keys:
                try:
                    for key in provides_keys:
                        mark_dependency_satisfied(flow_manager.state, key)
                except Exception:
                    pass

            # Return result without triggering a transition (None)
            return {"result": response_text}, None

        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.warning(
                "flow_a2a_call_timeout",
                skill_id=skill_id,
                timeout_seconds=timeout_seconds,
                elapsed_ms=round(elapsed_ms),
            )
            return {
                "error": True,
                "error_code": "A2A_TIMEOUT",
                "error_message": (
                    f"The {skill_id} service did not respond in time. "
                    "Please try again or help the caller directly."
                ),
            }, None

        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "flow_a2a_call_error",
                skill_id=skill_id,
                error=str(e),
                error_type=type(e).__name__,
                elapsed_ms=round(elapsed_ms),
            )
            return {
                "error": True,
                "error_code": "A2A_ERROR",
                "error_message": f"Error calling {skill_id}: {str(e)}",
            }, None

    # Set the function name and docstring dynamically so Flows extracts
    # the correct tool schema. The function name becomes the tool name
    # the LLM sees, and the docstring becomes the description.
    a2a_flow_function.__name__ = skill_id
    a2a_flow_function.__qualname__ = skill_id
    a2a_flow_function.__doc__ = f"""{description}

    Args:
        query: Natural language query for this capability. Be specific
            and include relevant context from the conversation.
    """

    # Protect A2A calls from barge-in cancellation. Without this,
    # FlowsDirectFunctionWrapper defaults cancel_on_interruption=True
    # and a user interruption mid-A2A-call would abort the in-flight request.
    a2a_flow_function._flows_cancel_on_interruption = False

    return a2a_flow_function


def _build_global_functions(
    session_id: str,
    transport: Any,
    sip_session_tracker: Optional[Dict[str, Optional[str]]] = None,
    collector: Optional[Any] = None,
    queue_frame: Optional[Callable] = None,
    available_capabilities: Optional[Any] = None,
) -> List[Callable]:
    """Build the list of global functions available in every node.

    Global functions are local voice pipeline tools (hangup, time, SIP
    transfer) wrapped as Pipecat Flows direct functions so they can be
    passed to FlowManager(global_functions=[...]).

    Args:
        session_id: Session ID for tool context
        transport: DailyTransport instance
        sip_session_tracker: Mutable dict tracking SIP session ID
        collector: Optional metrics collector
        queue_frame: Async callback to queue frames into the pipeline
        available_capabilities: Frozenset of detected capabilities

    Returns:
        List of async direct functions for global_functions parameter
    """
    from app.tools import ToolContext, ToolExecutor, ToolRegistry, PipelineCapability
    from app.tools.builtin.catalog import ALL_LOCAL_TOOLS

    if available_capabilities is None:
        available_capabilities = frozenset({PipelineCapability.BASIC})

    # Load the disabled-tools list
    disabled_tools: set = set()
    try:
        from app.services import get_config_service

        svc = get_config_service()
        if svc.is_configured():
            disabled_str = svc.config.features.disabled_tools
            if disabled_str:
                disabled_tools = {
                    name.strip() for name in disabled_str.split(",") if name.strip()
                }
    except Exception:
        pass

    # Filter tools and build executor
    registry = ToolRegistry()
    for tool in ALL_LOCAL_TOOLS:
        if tool.name in disabled_tools:
            continue
        tool_requires = tool.requires or frozenset({PipelineCapability.BASIC})
        if tool_requires <= available_capabilities:
            registry.register(tool)

    registry.lock()
    executor = ToolExecutor(registry, collector)

    # Create a Flows direct function wrapper for each local tool
    global_functions = []
    turn_counter = {"count": 0}

    for tool_def in registry.get_all_definitions():
        flow_fn = _create_local_tool_flow_function(
            tool_def=tool_def,
            executor=executor,
            session_id=session_id,
            transport=transport,
            sip_session_tracker=sip_session_tracker,
            collector=collector,
            queue_frame=queue_frame,
            turn_counter=turn_counter,
        )
        global_functions.append(flow_fn)

    logger.info(
        "flow_global_functions_built",
        function_count=len(global_functions),
        function_names=[fn.__name__ for fn in global_functions],
    )

    return global_functions


def _create_local_tool_flow_function(
    tool_def: Any,
    executor: Any,
    session_id: str,
    transport: Any,
    sip_session_tracker: Optional[Dict[str, Optional[str]]] = None,
    collector: Optional[Any] = None,
    queue_frame: Optional[Callable] = None,
    turn_counter: Optional[Dict[str, int]] = None,
) -> Callable:
    """Wrap a local ToolDefinition as a Pipecat Flows direct function.

    The wrapper adapts the existing ToolExecutor interface to the Flows
    direct function convention (flow_manager as first arg, returns tuple).

    IMPORTANT: Pipecat Flows uses ``inspect.signature()`` to extract the
    tool schema sent to the LLM.  If the wrapper uses ``**kwargs``, Flows
    creates a required parameter literally named ``"kwargs"`` with an
    empty JSON schema.  The LLM then calls e.g.
    ``hangup_call(kwargs={"reason": "..."})`` instead of
    ``hangup_call(reason="...")``.

    To fix this we keep the ``**kwargs`` wrapper for runtime flexibility
    but replace the function's ``__signature__`` with an explicit
    ``inspect.Signature`` whose parameters match the ToolDefinition.
    Flows reads ``inspect.signature()`` which respects ``__signature__``
    when present, so the LLM sees the correct named parameters.

    Args:
        tool_def: The ToolDefinition to wrap
        executor: ToolExecutor instance
        session_id: Session ID
        transport: DailyTransport
        sip_session_tracker: SIP session tracker
        collector: Metrics collector
        queue_frame: Frame queue callback
        turn_counter: Shared turn counter

    Returns:
        Async direct function for Pipecat Flows
    """
    import inspect as _inspect

    from app.tools import ToolContext

    tool_name = tool_def.name

    # Map ToolDefinition param types to Python types for annotations
    _type_map = {"string": str, "integer": int, "number": float, "boolean": bool}

    async def local_tool_flow_function(flow_manager: Any, **kwargs) -> tuple:
        """Local tool placeholder."""
        if turn_counter:
            turn_counter["count"] += 1

        context = ToolContext(
            call_id=session_id,
            session_id=session_id,
            turn_number=turn_counter["count"] if turn_counter else 0,
            metrics_collector=collector,
            transport=transport,
            sip_session_id=(
                sip_session_tracker["session_id"] if sip_session_tracker else None
            ),
            queue_frame=queue_frame,
        )

        result = await executor.execute(
            tool_name=tool_name,
            arguments=dict(kwargs),
            context=context,
        )

        if result.is_success():
            flow_result = result.content
        else:
            flow_result = {
                "error": True,
                "error_code": result.error_code or "TOOL_ERROR",
                "error_message": result.error_message or "Tool execution failed",
            }

        # Return (result, None) -- local tools don't trigger transitions
        return flow_result, None

    # Set function metadata from the tool definition
    local_tool_flow_function.__name__ = tool_name
    local_tool_flow_function.__qualname__ = tool_name

    # Build docstring with parameter descriptions for Flows schema extraction
    param_docs = []
    for param in tool_def.parameters:
        param_docs.append(f"        {param.name}: {param.description}")

    params_section = "\n".join(param_docs) if param_docs else "        (no parameters)"

    local_tool_flow_function.__doc__ = f"""{tool_def.description}

    Args:
{params_section}
    """

    # Build an explicit inspect.Signature so that Flows sees named params
    # instead of **kwargs.  Flows calls inspect.signature(func) which
    # respects __signature__ when set.
    sig_params = [
        _inspect.Parameter("flow_manager", _inspect.Parameter.POSITIONAL_OR_KEYWORD),
    ]
    annotations = {"flow_manager": Any, "return": tuple}

    for param in tool_def.parameters:
        py_type = _type_map.get(param.type, str)
        annotations[param.name] = py_type

        if param.required:
            sig_params.append(
                _inspect.Parameter(
                    param.name,
                    _inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=py_type,
                )
            )
        else:
            sig_params.append(
                _inspect.Parameter(
                    param.name,
                    _inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=None,
                    annotation=py_type,
                )
            )

    local_tool_flow_function.__signature__ = _inspect.Signature(
        sig_params, return_annotation=tuple
    )
    local_tool_flow_function.__annotations__ = annotations

    # Protect local tool calls from barge-in cancellation. Without this,
    # FlowsDirectFunctionWrapper defaults cancel_on_interruption=True
    # and a user interruption mid-tool-call would abort the in-flight request.
    local_tool_flow_function._flows_cancel_on_interruption = False

    return local_tool_flow_function


def _discover_agent_nodes(
    a2a_registry: Optional[Any],
    collector: Optional[Any] = None,
) -> Dict[str, Dict[str, Any]]:
    """Discover A2A agents and build node metadata for each.

    Iterates all agents in the registry, creates A2A flow functions for
    each agent's skills, and returns a dict of node metadata keyed by
    the slugified CloudMap service name.

    Also parses ``provides:`` and ``requires:`` tags from skill metadata
    to build the dependency graph used for transfer gating.

    Args:
        a2a_registry: AgentRegistry with discovered capabilities
        collector: Optional MetricsCollector

    Returns:
        Dict mapping node_name -> {
            "agent_name": str,
            "agent_description": str,
            "a2a_functions": list,
            "skill_ids": list,
            "provides": set,   -- dependency keys this agent can provide
            "requires": set,   -- dependency keys this agent needs
        }
    """
    if not a2a_registry:
        return {}

    from app.a2a.categories import resolve_tool_category

    nodes: Dict[str, Dict[str, Any]] = {}

    # Iterate all discovered agents (not skills -- we want one node per agent)
    # The _agent_cache maps url -> AgentEntry
    for agent_url, entry in a2a_registry._agent_cache.items():
        # Derive node name from CloudMap service name
        node_name = slugify_service_name(entry.endpoint.name)

        # Resolve a meaningful metrics category from the agent name
        agent_category = resolve_tool_category(entry.agent_name).value

        # Build A2A flow functions for this agent's skills
        a2a_fns = _build_a2a_flow_functions(
            skills=entry.skills,
            agent=entry.agent,
            a2a_timeout=float(a2a_registry.a2a_timeout),
            collector=collector,
            category=agent_category,
        )

        # Aggregate provides/requires tags across all skills
        skills_tags = [skill.tags for skill in entry.skills]
        agent_provides, agent_requires = aggregate_agent_tags(skills_tags)

        nodes[node_name] = {
            "agent_name": entry.agent_name,
            "agent_description": entry.agent_description,
            "a2a_functions": a2a_fns,
            "skill_ids": [s.skill_id for s in entry.skills],
            "provides": agent_provides,
            "requires": agent_requires,
        }

        logger.info(
            "flow_agent_node_discovered",
            node_name=node_name,
            agent_name=entry.agent_name,
            skill_count=len(entry.skills),
            skill_ids=[s.skill_id for s in entry.skills],
            provides=sorted(agent_provides) if agent_provides else [],
            requires=sorted(agent_requires) if agent_requires else [],
        )

    return nodes


def _register_all_node_factories(
    agent_nodes: Dict[str, Dict[str, Any]],
    agent_descriptions: Optional[Dict[str, str]] = None,
) -> None:
    """Register node factory functions for all discovered agents.

    Each factory is a zero-arg callable that returns a NodeConfig.
    The transition system uses these to create nodes on demand.

    Args:
        agent_nodes: Dict from _discover_agent_nodes()
        agent_descriptions: Dict mapping node names to descriptions
            (passed to orchestrator for routing context)
    """
    # Clear any stale registrations (important for per-call setup)
    clear_node_factories()

    # Register orchestrator (always present)
    # When transitioning back to orchestrator, is_return=True
    register_node_factory(
        "orchestrator",
        lambda: create_orchestrator_node(
            is_return=True,
            agent_descriptions=agent_descriptions,
        ),
    )
    register_node_factory(
        "reception",  # Alias for orchestrator
        lambda: create_orchestrator_node(
            is_return=True,
            agent_descriptions=agent_descriptions,
        ),
    )

    # Register one specialist node per discovered agent
    for node_name, meta in agent_nodes.items():
        # Capture meta in closure to avoid late-binding issues
        def make_factory(nm, m):
            return lambda: create_specialist_node(
                node_name=nm,
                agent_name=m["agent_name"],
                agent_description=m["agent_description"],
                a2a_functions=m["a2a_functions"],
                peer_descriptions=agent_descriptions,
                agent_requires=m.get("requires"),
            )

        register_node_factory(node_name, make_factory(node_name, meta))

    logger.info(
        "node_factories_registered",
        orchestrator=True,
        specialist_nodes=list(agent_nodes.keys()),
        total_targets=len(agent_nodes) + 2,  # +2 for orchestrator + reception alias
    )


def create_flow_manager(
    task: Any,
    llm: Any,
    context_aggregator: Any,
    transport: Any,
    session_id: str,
    sip_session_tracker: Optional[Dict[str, Optional[str]]] = None,
    collector: Optional[Any] = None,
    queue_frame: Optional[Callable] = None,
    a2a_registry: Optional[Any] = None,
    available_capabilities: Optional[Any] = None,
) -> FlowManager:
    """Create and configure a FlowManager for the voice pipeline.

    This is the main entry point for the Flows integration. It:
    1. Discovers A2A agents from the registry
    2. Creates specialist nodes dynamically from Agent Card data
    3. Builds global functions from local voice pipeline tools
    4. Registers node factories with the transition system
    5. Creates the FlowManager with the correct configuration

    The FlowManager is NOT initialized here -- call
    `flow_manager.initialize(node)` when the first participant joins.

    Args:
        task: PipelineTask instance
        llm: AWSBedrockLLMService instance
        context_aggregator: LLMContextAggregatorPair instance
        transport: DailyTransport instance
        session_id: Session ID for this call
        sip_session_tracker: Mutable dict tracking SIP session ID
        collector: Optional MetricsCollector
        queue_frame: Async callback to queue frames into the pipeline
        a2a_registry: Optional AgentRegistry for A2A capabilities
        available_capabilities: Frozenset of detected PipelineCapability values

    Returns:
        Configured FlowManager (not yet initialized)
    """
    # Discover agents and build node metadata
    agent_nodes = _discover_agent_nodes(a2a_registry, collector)

    # Build agent descriptions for the orchestrator's routing prompt
    agent_descriptions = {
        name: meta["agent_description"] for name, meta in agent_nodes.items()
    }

    # Register node factories (orchestrator + discovered specialists)
    _register_all_node_factories(agent_nodes, agent_descriptions)

    # Build global functions from local voice pipeline tools
    global_functions = _build_global_functions(
        session_id=session_id,
        transport=transport,
        sip_session_tracker=sip_session_tracker,
        collector=collector,
        queue_frame=queue_frame,
        available_capabilities=available_capabilities,
    )

    # Create the FlowManager (instrumented subclass for summary latency)
    flow_manager = InstrumentedFlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
        transport=transport,
        global_functions=global_functions if global_functions else None,
    )

    # Store collector in flow_manager.state so transfer() can access it
    # without changing its function signature (which is introspected by Flows).
    if collector:
        flow_manager.state["_collector"] = collector
        collector.set_agent_node("orchestrator")

    # Build dependency graph from agent tags and store in flow state.
    # provider_map: dep_key -> node_name that provides it
    # requirements_map: node_name -> set of dep_keys it requires
    provider_map: Dict[str, str] = {}
    requirements_map: Dict[str, set] = {}
    for name, meta in agent_nodes.items():
        for dep_key in meta.get("provides", set()):
            provider_map[dep_key] = name
        agent_reqs = meta.get("requires", set())
        if agent_reqs:
            requirements_map[name] = agent_reqs

    flow_manager.state["_provider_map"] = provider_map
    flow_manager.state["_requirements_map"] = requirements_map

    if provider_map or requirements_map:
        logger.info(
            "dependency_graph_built",
            provider_map={k: v for k, v in provider_map.items()},
            requirements_map={k: sorted(v) for k, v in requirements_map.items()},
        )

    logger.info(
        "flow_manager_created",
        session_id=session_id,
        global_function_count=len(global_functions),
        global_function_names=[fn.__name__ for fn in global_functions],
        discovered_agents=list(agent_nodes.keys()),
        agent_count=len(agent_nodes),
    )

    return flow_manager


def create_initial_node(
    a2a_registry: Optional[Any] = None,
) -> Any:
    """Create the initial node for the flow (orchestrator, first entry).

    This is used when initializing the FlowManager on first participant
    joined. Builds the orchestrator with dynamic agent descriptions so
    it knows what specialists are available.

    Args:
        a2a_registry: Optional AgentRegistry for building routing descriptions

    Returns:
        NodeConfig for the initial orchestrator node
    """
    # Build agent descriptions from the registry
    agent_descriptions: Optional[Dict[str, str]] = None
    if a2a_registry:
        agent_descriptions = {}
        for agent_url, entry in a2a_registry._agent_cache.items():
            node_name = slugify_service_name(entry.endpoint.name)
            agent_descriptions[node_name] = entry.agent_description

    return create_orchestrator_node(
        is_return=False,
        agent_descriptions=agent_descriptions,
    )
