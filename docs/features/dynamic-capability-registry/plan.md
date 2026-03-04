---
id: dynamic-capability-registry
name: Dynamic Capability Registry
type: feature
priority: P0
effort: Medium
impact: High
created: 2026-02-19
started: 2026-02-19
shipped: 2026-02-20
---

# Implementation Plan: Dynamic Capability Registry

## Overview

Replace the voice agent's hard-wired tool/observer/prompt assembly in `pipeline_ecs.py` with a dynamic, A2A-based capability architecture. Capabilities are independently deployed ECS Fargate services that self-register via AWS CloudMap and self-describe via standard A2A Agent Cards. The voice agent discovers capabilities at runtime and maps A2A skills to Pipecat tools. The LLM uses standard tool descriptions (auto-generated from Strands `@tool` docstrings) to reason about when and how to use each capability -- no custom prompt fragments needed.

**Key Design Principles:**
- **Independent deployment:** Each capability is its own CDK stack, deployable from any repo or team.
- **Self-announcing:** Capabilities register in CloudMap on ECS startup -- no custom registration code.
- **Self-describing:** Standard A2A Agent Cards at `/.well-known/agent-card.json` declare skills and schemas.
- **Model-driven tool use:** The voice agent LLM reasons about tool usage from Bedrock tool specs alone (descriptions, parameter schemas). No per-capability system prompt fragments -- aligns with Strands SDK's model-driven philosophy.
- **Hub-and-spoke + optional chaining:** Voice agent LLM orchestrates by default; capability agents can internally chain to other agents via A2A when intermediate steps are implementation details.
- **Protocol standard:** A2A (JSON-RPC 2.0 over HTTP) -- standard protocol via Strands SDK native A2A support.
- **Strands SDK for capability agents:** Each capability agent is a Strands `Agent` wrapped with `A2AServer`. No custom base agent package needed -- Strands handles Agent Card generation, FastAPI server, health endpoints, and A2A protocol compliance.

**Goal:** A new capability requires only deploying a new ECS service with a Strands agent and `A2AServer`. No edits to the voice agent codebase.

**Key Constraint -- Latency:** The voice agent pipeline (Pipecat) remains unchanged. `AWSBedrockLLMService` stays as the pipeline LLM, preserving token-level streaming to TTS and sub-second TTFB. The `StrandsAgentsProcessor` from pipecat PR #2610 is NOT used because it would break filler phrases, observers, and streaming granularity. Strands is used only for building the remote capability agents and for A2A client communication.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Voice Agent (ECS Fargate)                 │
│                                                                  │
│  Pipecat Pipeline (UNCHANGED):                                   │
│  DailyTransport → STT → Context → AWSBedrockLLMService          │
│      → [FunctionCallFillerProcessor] → TTS → DailyTransport     │
│                                                                  │
│  LLM emits tool_use ──▶ Pipecat tool handler                    │
│                              │                                   │
│                         ToolRouter                               │
│                         /         \                              │
│                 Core (local)    A2A Adapter                      │
│                 • transfer      • creates A2AAgent(endpoint)     │
│                 • diagnostics   • calls invoke_async(query)      │
│                                 • returns result to LLM          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ AgentRegistry (background polling, 30-60s)                  │ │
│  │  • polls CloudMap namespace                                  │ │
│  │  • creates A2AAgent instances per discovered endpoint        │ │
│  │  • fetches Agent Cards via A2AAgent.get_agent_card()         │ │
│  │  • builds skill → A2AAgent routing table                     │ │
│  │  • extracts Bedrock tool specs from skill descriptions       │ │
│  └─────────────────────────────────────────────────────────────┘ │
└──────────────────┬───────────────────────────────────────────────┘
                   │  A2A (JSON-RPC 2.0 / HTTP)
                   │  within VPC via CloudMap
     ┌─────────────┼─────────────┬─────────────┐
     ▼             ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ KB Agent │ │CRM Agent │ │ Future   │ │ Future   │
│ (ECS)    │ │ (ECS)    │ │ Agents   │ │ Agents   │
│          │ │          │ │          │ │          │
│ Strands  │ │ Strands  │ │ Strands  │ │ Any A2A  │
│ Agent +  │ │ Agent +  │ │ Agent +  │ │ Server   │
│ A2AServer│ │ A2AServer│ │ A2AServer│ │          │
│          │ │          │ │          │ │          │
│ CloudMap✓│ │ CloudMap✓│ │ CloudMap✓│ │ CloudMap✓│
│ AgentCard│ │ AgentCard│ │ AgentCard│ │ AgentCard│
│ (auto)   │ │ (auto)   │ │ (auto)   │ │          │
│          │ │          │ │          │ │          │
│ Skills:  │ │ Skills:  │ │          │ │          │
│ •search  │ │ •lookup  │ │          │ │          │
│  _kb     │ │ •cases   │ │          │ │          │
│          │ │ •verify  │ │          │ │          │
└──────────┘ └────┬─────┘ └──────────┘ └──────────┘
                  │ A2A (optional chaining)
                  ▼
            ┌──────────┐
            │Auth Agent│  (CRM agent internally
            │ (ECS)    │   chains to Auth when
            │          │   verification needed)
            └──────────┘
```

## Architecture Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | **Protocol** | A2A (JSON-RPC 2.0 over HTTP) | Standard agent protocol. Self-describing. Native support in Strands SDK 1.0+. |
| 2 | **Capability hosting** | ECS Fargate per capability | Always-on, no cold starts. CloudMap integration is built into ECS service config. |
| 3 | **Service discovery** | AWS CloudMap (HTTP namespace) | ECS auto-registers/deregisters services. Zero custom registration code. |
| 4 | **Self-description** | Standard A2A Agent Cards at `/.well-known/agent-card.json` | Auto-generated by Strands `A2AServer` from agent tools. No custom extensions -- stays A2A-compliant. |
| 5 | **Registry refresh** | Background polling every 30-60s | New capabilities appear within a minute. No per-call overhead. No restart required. |
| 6 | **Tool mapping** | Skill-level (1 A2A skill = 1 Pipecat tool) | LLM gets precise control. Consistent interface whether tool is local or remote. |
| 7 | **Prompt composition** | Model-driven (no prompt fragments) | LLM reasons about tool usage from Bedrock tool specs alone (name, description, parameter schemas). Tool descriptions are auto-generated from Strands `@tool` docstrings. Aligns with Strands model-driven philosophy. |
| 8 | **Core vs. dynamic** | Pipeline internals local. Domain logic remote via A2A. | Filler phrases, audio quality, transfer (needs DailyTransport), diagnostics stay in-process. KB, CRM are remote. |
| 9 | **Topology** | Hub-and-spoke + optional chaining | Voice agent LLM orchestrates. Agents can chain to other agents when intermediate steps are implementation details. |
| 10 | **Capability agent framework** | Strands SDK native A2A (`Agent` + `A2AServer`) | No custom base agent package. Strands auto-generates Agent Cards from tools, serves A2A endpoints, handles protocol compliance. ~10 lines per agent vs. ~200+ with custom framework. |
| 11 | **A2A client** | Strands `A2AAgent` class | No custom A2A HTTP client. `A2AAgent(endpoint=url)` handles card resolution, message building, response parsing. Supports both sync and streaming. |
| 12 | **Deployment** | Separate CDK stacks per capability | Any repo/team can create capabilities. Only need A2A contract + CloudMap namespace. |
| 13 | **Rollout** | Feature flag `ENABLE_CAPABILITY_REGISTRY` | Both legacy `_register_tools()` and new registry paths coexist until validated. |
| 14 | **Pipeline LLM** | Keep `AWSBedrockLLMService` (NOT `StrandsAgentsProcessor`) | `StrandsAgentsProcessor` (pipecat PR #2610) would break filler phrases, observers, and token streaming. Strands is only for remote agents. |

## Research Prerequisites

Before starting Phase 1, validate:

- [x] **R1:** Confirm `strands-agents[a2a]` package provides `A2AServer`, `A2AAgent`, and auto-generates Agent Cards from `@tool` definitions. Pin version `>=1.27.0`. **VALIDATED** (spike 2026-02-19). Agent Card auto-generated with skills from `@tool` docstrings. Skill fields: `id`, `name`, `description`, `tags`. NOTE: Skills do NOT include `input_schema` -- tool spec generation must use a single `query: str` parameter pattern (Option D). Agent Card served at `/.well-known/agent-card.json` (not `agent.json`).
- [ ] **R2:** Verify Pipecat tool handlers can have variable latency without blocking the pipeline. A2A calls will be 50-300ms vs. <50ms for local tools. The filler phrase system should handle this, but confirm.
- [ ] **R3:** Test CloudMap `DiscoverInstances` latency from within VPC. Target: <20ms.
- [ ] **R4:** Confirm ECS Fargate tasks auto-register/deregister in CloudMap reliably on deploy/rollback/scale events.
- [ ] **R5:** Evaluate `transfer_tool` -- it currently requires the Pipecat `DailyTransport` object for SIP REFER. Decision: keep local (see Architecture Decision #8).
- [x] **R6:** Validate that `A2AAgent.invoke_async()` response can be mapped to a dict suitable for Pipecat's `result_callback()`. **VALIDATED** (spike 2026-02-19). `AgentResult.message` = `{"role": "assistant", "content": [{"text": "..."}]}`. Extract text from content blocks and pass to `result_callback([{"type": "text", "text": extracted_text}])`. `str(result)` also works as a shorthand. Latency: ~3.3s per call (includes agent LLM reasoning).

## Implementation Steps

### Phase 1: Core Framework -- CloudMap Discovery & Agent Registry

Build the voice agent's capability discovery layer. A2A protocol handling is delegated to Strands SDK.

**1.1 CloudMap discovery**
- [ ] Create `backend/voice-agent/app/a2a/__init__.py` -- public exports
- [ ] Create `backend/voice-agent/app/a2a/discovery.py` -- CloudMap service discovery
  - Port pattern from workshop `lib/agents/discover_agent.py`
  - `async discover_agents(namespace: str) -> list[AgentEndpoint]` -- list all services
  - Use async boto3 (`aiobotocore`) for CloudMap API calls
  - Return list of `AgentEndpoint(name, url)` for each healthy service
  - Handle unhealthy/unreachable agents gracefully (skip with warning)

**1.2 Implement AgentRegistry with background polling**
- [ ] Create `backend/voice-agent/app/a2a/registry.py` -- capability registry
  - `AgentRegistry` class with:
    - `async start_polling(interval_seconds: int = 30)` -- background asyncio task
    - `async refresh()` -- discover agents via CloudMap -> create `A2AAgent(endpoint=url)` per agent -> fetch Agent Cards via `a2a_agent.get_agent_card()` -> rebuild routing table
    - `get_routing_table() -> dict[str, A2AAgentEntry]` -- skill_id -> (A2AAgent instance, AgentCard, skill metadata)
    - `get_tool_definitions() -> list[dict]` -- skill -> Bedrock tool spec (extracted from Agent Card skill descriptions + input schemas)
    - `get_agent_cards() -> list[AgentCard]` -- all discovered cards
    - `stop_polling()` -- graceful shutdown
  - Thread-safe routing table swap (atomically replace dict reference)
  - Logging: log capability additions/removals on each refresh
  - Caches `A2AAgent` instances across polling cycles (recreate only on endpoint change)

**1.3 Unit tests for core framework**
- [ ] `backend/voice-agent/tests/test_a2a_discovery.py` -- mock CloudMap API, unhealthy agent handling
- [ ] `backend/voice-agent/tests/test_a2a_registry.py` -- routing table build, tool definition extraction, polling lifecycle, agent caching

### Phase 2: Pipecat Integration -- A2A Tool Adapter

Bridge A2A capabilities into Pipecat's tool calling flow.

**2.1 A2A tool adapter**
- [ ] Create `backend/voice-agent/app/a2a/tool_adapter.py`
  - `create_a2a_tool_handler(skill_id: str, a2a_agent: A2AAgent) -> Callable`
    - Returns an async function matching Pipecat's `register_function` handler signature:
      `async (function_name, tool_call_id, args, llm_service, context, result_callback)`
    - Builds query string from `args` dict
    - Calls `await a2a_agent.invoke_async(query)`
    - Extracts text/data from `AgentResult.message` content blocks
    - Returns result via `result_callback()`
    - Handles timeouts and errors -> error result dict
    - Respects pipeline cancellation (barge-in)
  - `extract_bedrock_tool_spec(skill: AgentSkill) -> dict`
    - Maps A2A `AgentSkill` to Bedrock `toolSpec` format
    - Uses skill description as tool description
    - **Input schema:** Agent Card skills do NOT include input_schema (validated in R1 spike). Each A2A tool uses a single `query: str` parameter -- the A2A agent receives natural language and handles parameter extraction internally
    - Bedrock tool spec: `{"name": skill.id, "description": skill.description, "inputSchema": {"json": {"type": "object", "properties": {"query": {"type": "string", "description": "Natural language query for this capability"}}, "required": ["query"]}}}`

**2.2 Integrate with pipeline_ecs.py**
- [ ] Add `ENABLE_CAPABILITY_REGISTRY` env var (default: `false`)
- [ ] New function: `async _register_capabilities(llm, session_id, transport, collector, sip_tracker) -> list[dict]`
  - Returns `bedrock_tool_specs` (list of Bedrock-format tool definitions)
  - Gets `AgentRegistry` singleton (started during service init)
  - Calls `registry.get_tool_definitions()` to get remote tool specs
  - For each remote skill, creates A2A tool handler via `create_a2a_tool_handler()` and registers with LLM via `llm.register_function()`
  - Also registers core local tools (transfer, diagnostics) directly as today
  - Returns combined tool specs (local + remote)
- [ ] Modify `create_voice_pipeline()`:
  - When flag enabled: call `_register_capabilities()` instead of `_register_tools()`
  - System prompt stays as-is (base prompt + TTS instructions). No per-capability prompt fragments.
  - When flag disabled: existing `_register_tools()` path unchanged
- [ ] Modify `service_main.py`:
  - Start `AgentRegistry.start_polling()` at service startup
  - Stop polling on shutdown

**2.3 Integration tests**
- [ ] `backend/voice-agent/tests/test_a2a_tool_adapter.py` -- adapter produces correct Bedrock tool specs, handles A2A success/error/timeout, barge-in cancellation
- [ ] `backend/voice-agent/tests/test_a2a_pipeline_integration.py` -- full pipeline assembly with mocked registry, verify tool registration, verify combined local+remote tool specs

### Phase 3: Infrastructure -- CloudMap Namespace & Capability Stack Template

**3.1 Add CloudMap namespace to voice agent core stack**
- [ ] File: `infrastructure/src/constructs/` -- new construct or modify ECS construct
  - Create `AWS::ServiceDiscovery::HttpNamespace` (e.g., `voice-agent-capabilities`)
  - Export namespace ID and namespace name via SSM parameters:
    - `/voice-agent/capabilities/namespace-id`
    - `/voice-agent/capabilities/namespace-name`
  - Grant voice agent ECS task role `servicediscovery:DiscoverInstances`, `servicediscovery:ListServices`

**3.2 Create CDK construct for capability agent stacks**
- [ ] File: `infrastructure/src/constructs/capability-agent-construct.ts`
  - Reusable CDK construct that creates:
    - ECS Fargate task definition + service
    - CloudMap service registration (imports namespace from SSM)
    - CloudWatch log group
    - IAM task role with Bedrock access (configurable)
    - Health check configuration (`/health` endpoint)
    - Security group allowing inbound from voice agent
  - Props: `agentName`, `agentType`, `containerImage`, `cpu`, `memory`, `environment`, etc.

**3.3 Infrastructure tests**
- [ ] CDK construct snapshot tests for CloudMap namespace
- [ ] CDK construct snapshot tests for capability agent construct

### Phase 4: Migrate First Capability -- Knowledge Base Agent

Prove the architecture by extracting KB into a standalone A2A agent.

**4.1 Create KB agent service**
- [ ] Directory: `backend/agents/knowledge-base-agent/`
  - `main.py` -- Strands agent with `A2AServer`:
    ```python
    from strands import Agent, tool
    from strands.models import BedrockModel
    from strands.multiagent.a2a import A2AServer

    @tool
    def search_knowledge_base(query: str, max_results: int = 3) -> dict:
        """Search the knowledge base for information about products, policies,
        procedures, or other documentation. Use this when the user asks questions
        that might be answered by company documentation, FAQs, or reference
        materials. Always cite the source when presenting information.

        Args:
            query: Natural language search query. Be specific for better results.
            max_results: Maximum results to return (1-5, default 3).
        """
        # ... KB retrieval logic (ported from app/services/knowledge_base_service.py) ...

    agent = Agent(
        name="Knowledge Base Agent",
        description="Searches enterprise knowledge base for product, policy, and procedure information",
        model=BedrockModel(model_id="..."),
        tools=[search_knowledge_base],
    )
    a2a_server = A2AServer(agent=agent, host="0.0.0.0", port=8080)
    a2a_server.serve()
    ```
  - `Dockerfile` for container image
  - `requirements.txt`: `strands-agents[a2a]>=1.27.0`, `boto3`
  - Note: The `@tool` docstring IS the tool description that the voice agent's LLM will see. It must be explicit about when/how to use the tool.

**4.2 Create KB agent CDK stack**
- [ ] File: `infrastructure/src/stacks/kb-agent-stack.ts`
  - Uses `CapabilityAgentConstruct`
  - Passes KB-specific environment: `KB_KNOWLEDGE_BASE_ID` (from SSM), `KB_RETRIEVAL_MAX_RESULTS`, `KB_MIN_CONFIDENCE_SCORE`
  - Grants Bedrock KB query permissions to task role
  - Deployable independently from voice agent stack

**4.3 Validate end-to-end**
- [ ] Deploy KB agent stack
- [ ] Verify CloudMap registration (agent appears in namespace)
- [ ] Verify Agent Card auto-generated at `/.well-known/agent-card.json` (served by Strands A2AServer)
- [ ] Deploy voice agent with `ENABLE_CAPABILITY_REGISTRY=true`
- [ ] Verify voice agent discovers KB agent via AgentRegistry polling
- [ ] Verify LLM can call `search_knowledge_base` via A2A
- [ ] Compare latency vs. local tool execution (target: <50ms added overhead)
- [ ] Verify LLM uses tool appropriately without custom prompt fragment (model-driven)

### Phase 5: Migrate Remaining Capabilities

**5.1 CRM Agent**
- [ ] `backend/agents/crm-agent/` -- Strands agent with 5 `@tool` functions: `customer_lookup`, `create_case`, `add_case_note`, `verify_account_number`, `verify_recent_transaction`
- [ ] `infrastructure/src/stacks/crm-agent-stack.ts`
- [ ] Port `SimpleCRMService` HTTP calls into `@tool` implementations
- [ ] Test: all 5 CRM tools discovered and work via A2A

**5.2 Transfer & Diagnostics -- Stay Local**
- [ ] `transfer_tool` remains local (requires `DailyTransport` for SIP REFER)
- [ ] `time_tool` remains local (trivial, no benefit from A2A overhead)
- [ ] Diagnostic tools (`random_number`, `slow_random`) remain local (testing tools)
- [ ] These are registered directly via existing `_register_tools()` pattern within `_register_capabilities()`

### Phase 6: Documentation & Rollout

**6.1 Developer documentation**
- [ ] How to create a new capability agent with Strands SDK (step-by-step guide)
  - Define `@tool` functions with explicit docstrings
  - Create `Agent(tools=[...])` + `A2AServer(agent=...)`
  - Dockerfile + requirements.txt
  - CDK stack using `CapabilityAgentConstruct`
  - Deploy -- voice agent discovers it automatically
- [ ] CDK construct usage for `CapabilityAgentConstruct`
- [ ] Architecture diagram and data flow
- [ ] Tool description best practices (since LLM relies on descriptions alone, no prompt fragments)

**6.2 Update CLAUDE.md**
- [ ] Add `ENABLE_CAPABILITY_REGISTRY` env var
- [ ] Add `CLOUDMAP_NAMESPACE` env var
- [ ] Add `CAPABILITY_POLL_INTERVAL_SECONDS` env var
- [ ] Document new CloudWatch metrics for A2A calls
- [ ] Note: `strands-agents[a2a]>=1.27.0` dependency for capability agents

**6.3 Remove legacy code path**
- [ ] After production validation, make capability registry the default
- [ ] Remove `_register_tools()` and inline KB prompt assembly from `pipeline_ecs.py`
- [ ] Remove feature flag
- [ ] Update all tests

## Open Questions

| Question | Impact | Resolution Needed By |
|----------|--------|---------------------|
| Can `A2AAgent.invoke_async()` return structured data (dicts), or only text? | Phase 2 adapter design | Before Phase 2 |
| Should diagnostic tools be removed entirely in the registry path? | Phase 5.2 scope | Before Phase 5 |
| How to handle agent card schema versioning as Strands SDK evolves? | Future compat | Before Phase 6 |
| Should we add circuit-breaking for unhealthy A2A agents? | Resilience | Phase 2 or later |
| Per-call capability sets (different tools per call)? | Future feature | Deferred |
| MCP gateway support (like workshop's MCP bridge)? | Ecosystem | Deferred |
| Will model-driven tool use (no prompt fragments) work well with Haiku for nuanced tools? | Tool use quality | Validate in Phase 4.3 |

## Testing Strategy

1. **Unit Tests:** CloudMap discovery, AgentRegistry polling/caching, A2A tool adapter -- all with mocked dependencies.
2. **Integration Tests:** Full pipeline assembly with mocked registry. Verify Bedrock tool specs match format. Verify combined local+remote tool registration.
3. **Contract Tests:** Validate A2A request/response format. Validate Agent Card structure from `A2AServer`.
4. **Backward Compatibility:** Assert capability-based registration produces same LLM behavior as `_register_tools()`.
5. **E2E Tests:** Deploy KB agent + voice agent with registry enabled. Place SIP test call. Verify KB tool works via A2A.
6. **Latency Tests:** Measure A2A overhead vs. local tool execution. Target: <50ms added per tool call.
7. **Model-Driven Validation:** Verify LLM correctly uses tools based on descriptions alone, without custom prompt fragments. Compare tool invocation accuracy vs. current prompt-augmented approach.

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| A2A network latency degrades voice UX | Higher E2E latency | Measure. Within-VPC calls should add <30ms. Filler phrases cover delays. |
| Agent discovery polling misses a new capability | Capability unavailable for up to 60s | Acceptable for deploy-time changes. Add manual refresh endpoint if needed. |
| CloudMap unhealthy instance lingers | Voice agent calls dead endpoint | Health check + timeout + skip unhealthy in discovery. Circuit breaker later. |
| Transfer tool can't go remote (needs DailyTransport) | Transfer stays local, hybrid architecture | Keep as core local tool. Not a blocker -- validates that core/dynamic split works. |
| Strands SDK A2A API changes | Breaking changes on upgrade | Pin version. Monitor Strands releases. SDK reached 1.0 stability. |
| Model-driven tool use less accurate than prompt-augmented | LLM misuses tools or doesn't use them when it should | Write thorough `@tool` docstrings. Validate in Phase 4.3. Fall back to adding base prompt hints if needed (still no per-capability fragments). |
| `A2AAgent` response format doesn't map cleanly to Pipecat tool results | Adapter complexity | Research prerequisite R6. Worst case: extract text from response and return as string result. |
| Over-engineering for current 3-4 capabilities | Wasted effort | Phase 4 (first migration) is the validation point. If too complex, simplify. |

## Dependencies

- `tool-calling-framework` (shipped) -- Foundation for ToolDefinition, ToolRegistry, ToolExecutor
- `knowledge-base-rag` (shipped) -- First capability to extract
- `smart-transfer-tool` (shipped) -- Stays local (needs DailyTransport)
- `simple-crm-system` (shipped) -- Second capability to extract
- `strands-agents[a2a]>=1.27.0` -- Strands SDK with A2A support (for capability agents + `A2AAgent` client)
- `a2a` Python package -- Transitive dependency via strands-agents[a2a]
- Workshop code at `/workshops/inter-agent-systems-with-strands-agents-amazon-bedrock-mcp-and-a2a` -- reference patterns for CloudMap discovery (note: workshop uses manual HTTP requests, not Strands `A2AAgent` client)
- Pipecat framework -- Must confirm variable-latency tool handler support
- AWS CloudMap -- HTTP namespace for service discovery

## File Structure

```
backend/
  voice-agent/app/
    a2a/                              # A2A integration for voice agent
      __init__.py                     # Public API exports
      discovery.py                    # CloudMap discovery (list agents, get endpoints)
      registry.py                     # AgentRegistry with background polling + A2AAgent caching
      tool_adapter.py                 # A2AAgent -> Pipecat tool handler adapter

  agents/                             # Individual capability agents (Strands + A2AServer)
    knowledge-base-agent/
      main.py                         # Strands Agent + A2AServer (~50 lines)
      Dockerfile
      requirements.txt                # strands-agents[a2a]>=1.27.0, boto3
    crm-agent/
      main.py                         # Strands Agent with 5 @tool functions + A2AServer
      Dockerfile
      requirements.txt

infrastructure/src/
  constructs/
    capability-agent-construct.ts     # Reusable CDK construct for capability ECS services
  stacks/
    kb-agent-stack.ts                 # Knowledge Base agent stack
    crm-agent-stack.ts                # CRM agent stack
```

Note: No `capability-agent-base/` package needed. Strands SDK provides the base agent framework, A2A server, Agent Card generation, and protocol handling. Each capability agent is self-contained with just `strands-agents[a2a]` as a dependency.

## Success Criteria

- [ ] CloudMap discovery finds all running capability agents
- [ ] Agent Cards auto-generated by Strands `A2AServer` (standard A2A format)
- [ ] AgentRegistry refreshes every 30-60s via background polling, caches `A2AAgent` instances
- [ ] A2A skills appear as Pipecat tools to the LLM (Bedrock tool spec format)
- [ ] LLM correctly uses tools based on descriptions alone (model-driven, no prompt fragments)
- [ ] KB agent deployed as independent Strands agent stack, works via A2A
- [ ] CRM agent deployed as independent Strands agent stack, works via A2A
- [ ] Adding a new capability requires only deploying a new ECS service -- no voice agent changes
- [ ] E2E voice latency increase <50ms per A2A tool call (within VPC)
- [ ] Filler phrases work correctly for A2A tool calls (same as local tools)
- [ ] All existing tests pass with both legacy and registry code paths
- [ ] Developer docs explain how to create a new capability agent with Strands SDK

## Estimated Effort

| Phase | Effort |
|-------|--------|
| Research prerequisites (R1-R6) | 0.5 day |
| Phase 1: CloudMap discovery + AgentRegistry | 1.5 days |
| Phase 2: Pipecat integration (tool adapter, pipeline) | 1.5 days |
| Phase 3: Infrastructure (CloudMap, CDK construct) | 2 days |
| Phase 4: First migration -- KB agent | 1 day |
| Phase 5: CRM agent migration | 1.5 days |
| Phase 6: Documentation & rollout | 1 day |
| **Total** | **~9 days** |

Buffer for Strands A2A integration surprises, latency tuning: +2 days
**Risk-adjusted total:** ~11 days (~2 weeks)

## Progress Log

| Date | Update |
|------|--------|
| 2026-02-19 | Initial plan created (local plugin approach). |
| 2026-02-19 | Plan rewritten: shifted to A2A-based approach with CloudMap discovery, independent ECS deployment, and workshop pattern reuse. |
| 2026-02-19 | Plan revised: adopted Strands SDK native A2A support. Eliminated custom A2A client, base agent package, and systemPromptFragment in favor of model-driven tool use. Reduced effort from ~15 days to ~9 days. Decision: keep Pipecat pipeline LLM unchanged (AWSBedrockLLMService) for latency; use Strands only for remote capability agents. Evaluated pipecat PR #2610 (StrandsAgentsProcessor) -- rejected for pipeline use due to filler phrase/observer/streaming incompatibility. |
| 2026-02-19 | **R1/R6 spike completed.** Validated strands-agents==1.27.0 with a2a-sdk==0.3.23. Agent Card auto-generates from `@tool` docstrings (skills have id/name/description but no input_schema). `AgentResult.message` = `{"role": "assistant", "content": [{"text": "..."}]}` maps cleanly to Pipecat `result_callback`. Key finding: skills lack input_schema, so Bedrock tool specs use single `query: str` parameter pattern. Updated version pin to >=1.27.0, Agent Card endpoint to `/.well-known/agent-card.json`. See `backend/spikes/strands-a2a-spike/FINDINGS.md`. |
| 2026-02-19 | **Phase 1 complete.** CloudMap discovery (`discovery.py`) + AgentRegistry (`registry.py`) + Tool Adapter (`tool_adapter.py`) implemented with 43 unit tests passing. |
| 2026-02-20 | **Phase 2 complete.** Pipeline integration wiring finished. Added `A2AConfig` dataclass and `enable_capability_registry` feature flag to config service (SSM + env var fallback). Created `_register_capabilities()` function in `pipeline_ecs.py` that merges local tools with remote A2A capabilities (local tools take precedence on name conflicts). Modified `create_voice_pipeline()` with feature-flag-gated routing: registry path when enabled, legacy `_register_tools()` when disabled. Modified `service_main.py` to create `AgentRegistry` on startup, start polling in `run_server()`, and stop on shutdown. 22 new integration tests covering: `_register_capabilities()` (merge, conflict, empty), config (SSM params, env fallback, defaults), pipeline routing (flag on/off), service lifecycle (create/start/stop/none). Full suite: **404 tests pass, 0 failures.** |
| 2026-02-20 | **Phase 3 complete.** Infrastructure CDK for CloudMap and capability agent construct. Created CloudMap HTTP namespace in ECS stack (`capabilityNamespace` property) with SSM params for namespace ID/name. Added `servicediscovery:DiscoverInstances` + `servicediscovery:ListServices` IAM permissions on voice agent task role. Created reusable `CapabilityAgentConstruct` in `infrastructure/src/constructs/capability-agent-construct.ts` — accepts `IHttpNamespace` (works with both same-stack and cross-stack refs). Uses L1 `CfnService` + `Service.fromServiceAttributes()` + `associateCloudMapService()` pattern for HTTP namespace CloudMap registration. Creates: SG with voice agent ingress, log group, IAM task/execution roles, Fargate task def + service. 21 new CDK tests pass. |
| 2026-02-20 | **Phase 4 complete.** KB Agent migration — code and infrastructure done. Created `backend/agents/knowledge-base-agent/` (main.py, Dockerfile, requirements.txt): Strands A2A agent with `@tool search_knowledge_base` wrapping Bedrock KB retrieval via sync boto3. Created `infrastructure/src/stacks/kb-agent-stack.ts` using `CapabilityAgentConstruct` with KB env vars and Bedrock KB retrieval IAM policy. Added to `main.ts` as Phase 9. 9 new CDK tests pass. **Total CDK tests: 107 (30 new, 3 pre-existing failures unrelated to our changes).** Phase 4.3 validation items (actual deployment) deferred to deployment phase. |
| 2026-02-20 | **Phase 5 complete.** CRM Agent migration — code and infrastructure done. Created `backend/agents/crm-agent/` with 4 files: `crm_client.py` (sync HTTP client ported from `SimpleCRMService`'s async/aiohttp to sync/requests for Strands `@tool` compatibility), `main.py` (Strands A2A agent with 5 `@tool` functions: `lookup_customer`, `create_support_case`, `add_case_note`, `verify_account_number`, `verify_recent_transaction`), `Dockerfile`, `requirements.txt`. Created `infrastructure/src/stacks/crm-agent-stack.ts` using `CapabilityAgentConstruct` with `CRM_API_URL` env var from SSM, Bedrock model access enabled (for agent reasoning), no additional IAM policies (CRM API accessed via outbound HTTPS). Added to `main.ts` as Phase 10 with dependencies on `ecsStack` + `crmStack`. 9 new CDK tests pass covering: task def, ECS service, CRM_API_URL env var, Bedrock model permissions, NO KB permissions, CloudMap service, SG ingress, log group, service name output. **Total CDK tests: 126 (39 new across Phases 3-5, 3 pre-existing failures unrelated to our changes).** |
