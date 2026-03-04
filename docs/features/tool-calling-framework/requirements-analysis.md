# Tool Calling Framework - Requirements Analysis

**Document Version**: 1.0
**Status**: Draft
**Last Updated**: 2026-01-27
**Author**: ProductVisionary (Requirements Analysis)

---

## Executive Summary

This document provides a comprehensive requirements analysis for implementing a Tool Calling Framework in the voice agent. The feature enables the agent to execute real actions during conversations, transforming it from a simple conversational bot into a functional customer support system.

**Business Value**: Without tool calling, the agent can only generate generic responses. With it, the agent can look up accounts, check order status, create tickets, and interact with business systems in real-time.

---

## 1. Requirements Completeness Validation

### 1.1 Original Requirements Assessment

The original idea document (`/docs/features/tool-calling-framework/idea.md`) covers:

| Requirement Area | Coverage | Gap Assessment |
|-----------------|----------|----------------|
| Tool Definition Format | Complete | Name, description, JSON schema, executor |
| Tool Parsing | Partial | Mentions Bedrock tool_use blocks but lacks streaming details |
| Tool Execution | Partial | Timeouts mentioned, but no retry/circuit breaker strategy |
| Result Integration | Complete | Returns results to LLM for synthesis |
| Error Handling | Partial | "Graceful degradation" mentioned but not specified |
| Audit Logging | Complete | Compliance logging mentioned |

### 1.2 Missing Edge Cases Identified

#### Critical Edge Cases

| Edge Case | Description | Recommended Handling |
|-----------|-------------|---------------------|
| **Tool Timeout During Speech** | Tool takes >3s while user is listening | Integrate with conversational-delay-handling; speak filler phrase |
| **Tool Returns Empty Result** | External API returns 200 but no data | Synthesize "I couldn't find that information" response |
| **Tool Returns Partial Data** | Some fields missing from API response | LLM should handle gracefully; validate schema |
| **Concurrent Tool Requests** | LLM requests 2+ tools in same response | Support parallel execution with Promise.all pattern |
| **Tool Call During Barge-In** | User interrupts while tool executing | Cancel tool execution; preserve context for retry |
| **Tool Requires Confirmation** | Destructive actions (create ticket) | Implement confirmation pattern before execution |
| **Rate Limited External API** | Tool hits rate limit | Exponential backoff with user notification |
| **Authentication Failure** | API credentials expired mid-call | Graceful error message; log for ops alert |
| **Tool Returns Large Response** | API returns >100KB response | Truncate/summarize before passing to LLM context |
| **Invalid Tool Parameters** | LLM provides malformed params | Schema validation before execution; re-prompt LLM |

#### Tool Chaining Scenarios

| Scenario | Example | Complexity |
|----------|---------|------------|
| **Sequential Dependency** | `get_customer_id` -> `get_order_status(customer_id)` | Medium - Requires state management between calls |
| **Conditional Chaining** | If account exists, get orders; else create account | High - LLM handles logic, but needs context preservation |
| **Aggregation** | Get orders from 3 systems, combine results | Medium - Parallel execution with result merging |

**Recommendation**: MVP should support sequential tool calls (LLM-orchestrated). Parallel execution can be Phase 2.

### 1.3 Parallel Tool Execution Analysis

The Bedrock Converse API can return multiple `tool_use` blocks in a single response. Pipecat's base `LLMService` supports both parallel and sequential execution modes.

```python
# Bedrock can return multiple tool_use blocks:
{
  "output": {
    "message": {
      "content": [
        {"toolUse": {"toolUseId": "1", "name": "get_customer", ...}},
        {"toolUse": {"toolUseId": "2", "name": "get_orders", ...}}
      ]
    }
  },
  "stopReason": "tool_use"
}
```

**Recommendation**:
- MVP: Sequential execution (simpler, lower latency variance)
- Phase 2: Parallel execution for independent tools

---

## 2. Risk Assessment & Dependencies

### 2.1 External Service Dependencies

| Dependency | Impact | Mitigation |
|------------|--------|------------|
| **Bedrock Converse API** | Critical - Core functionality | Already proven in codebase; tool_use is supported |
| **External APIs (CRM, Order System)** | High - Feature value | Circuit breaker pattern; fallback responses |
| **DynamoDB (if used for tool state)** | Medium - Audit logging | Async writes; don't block on logging failures |

### 2.2 Latency Impact Analysis

Current pipeline latency breakdown (from observability data):

| Component | Typical Latency | With Tool Calling |
|-----------|----------------|-------------------|
| STT | ~150ms | ~150ms (no change) |
| LLM TTFB | ~300ms | ~400ms (tool definitions add context) |
| Tool Execution | N/A | **+500-3000ms** (variable) |
| LLM Response Synthesis | N/A | **+200-400ms** (additional LLM call) |
| TTS TTFB | ~90ms | ~90ms (no change) |
| **Total E2E** | ~500-700ms | **~1200-4000ms** |

**Critical Insight**: Tool calling can increase E2E latency by 2-8x. This makes `conversational-delay-handling` feature a **hard dependency** for acceptable user experience.

### 2.3 Security Considerations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Prompt Injection via Tool Results** | High | Sanitize tool results before LLM context; use structured data |
| **Unauthorized Tool Execution** | High | Whitelist tools per session; role-based tool access |
| **Sensitive Data Exposure** | Medium | Redact PII from audit logs; don't log full tool results |
| **Tool Parameter Manipulation** | Medium | Strict JSON schema validation; type coercion |
| **Denial of Service (tool loops)** | Medium | Max tool calls per turn (e.g., 5); max per session (e.g., 50) |

### 2.4 Dependency Graph

```
                    ┌─────────────────────────────────┐
                    │   tool-calling-framework (P0)   │
                    └─────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
    ┌───────────────────┐  ┌──────────────┐  ┌──────────────────┐
    │ conversational-   │  │ External API │  │ Audit/Compliance │
    │ delay-handling    │  │ Integrations │  │ Logging          │
    │ (HARD DEPENDENCY) │  │ (Soft)       │  │ (Soft)           │
    └───────────────────┘  └──────────────┘  └──────────────────┘
            │
            │ Enables
            ▼
    ┌───────────────────┐
    │ knowledge-base-   │
    │ rag (can use      │
    │ tool pattern)     │
    └───────────────────┘
```

---

## 3. Acceptance Criteria

### 3.1 Functional Acceptance Criteria

#### Tool Registration (Must Have)

- [ ] **AC-1.1**: Tools can be registered at pipeline startup via declarative configuration
- [ ] **AC-1.2**: Each tool has: name (unique), description, JSON schema for parameters, async executor function
- [ ] **AC-1.3**: Tool registry validates tool definitions at startup (fail fast on invalid schema)
- [ ] **AC-1.4**: Tools can be enabled/disabled per session via configuration

#### Tool Invocation (Must Have)

- [ ] **AC-2.1**: When Bedrock returns `stopReason: "tool_use"`, framework parses `toolUse` blocks
- [ ] **AC-2.2**: Tool parameters are validated against JSON schema before execution
- [ ] **AC-2.3**: Invalid parameters result in error response to LLM (not user-facing error)
- [ ] **AC-2.4**: Tool executor is called with validated parameters and session context

#### Tool Execution (Must Have)

- [ ] **AC-3.1**: Each tool has configurable timeout (default: 5s, max: 30s)
- [ ] **AC-3.2**: Tool execution runs in isolated async context (doesn't block pipeline)
- [ ] **AC-3.3**: Timeout results in structured error returned to LLM
- [ ] **AC-3.4**: Exceptions are caught and converted to structured errors for LLM

#### Result Integration (Must Have)

- [ ] **AC-4.1**: Tool results are formatted as `toolResult` blocks per Bedrock spec
- [ ] **AC-4.2**: Results are appended to conversation context and LLM is re-invoked
- [ ] **AC-4.3**: LLM synthesizes natural language response incorporating tool results
- [ ] **AC-4.4**: Maximum 3 tool-calling rounds per turn (prevent infinite loops)

#### Error Handling (Must Have)

- [ ] **AC-5.1**: Tool failures result in graceful user-facing message (e.g., "I couldn't look that up right now")
- [ ] **AC-5.2**: Error responses include category for metrics (timeout, auth, not_found, internal)
- [ ] **AC-5.3**: Partial failures in parallel execution don't crash entire request

#### Audit Logging (Must Have)

- [ ] **AC-6.1**: All tool invocations logged with: tool_name, session_id, call_id, timestamp
- [ ] **AC-6.2**: Tool parameters logged (with PII redaction rules)
- [ ] **AC-6.3**: Tool results logged (summary only, not full response)
- [ ] **AC-6.4**: Tool duration and status logged for metrics

### 3.2 Performance Requirements

| Metric | Requirement | Measurement |
|--------|-------------|-------------|
| **Tool Overhead** | <100ms added latency for tool parsing/routing | Measure time from LLM response to tool executor start |
| **Tool Execution P50** | <1000ms for simple lookups | CloudWatch metric per tool |
| **Tool Execution P99** | <5000ms including retries | CloudWatch metric per tool |
| **E2E with Tool Call** | <3000ms from VAD stop to first TTS audio | E2E latency metric with tool_used dimension |
| **Filler Phrase Trigger** | <1500ms from tool start | Requires conversational-delay-handling |
| **Memory Overhead** | <50MB per registered tool | Monitor container memory |

### 3.3 Non-Functional Requirements

| Requirement | Specification |
|-------------|---------------|
| **Observability** | Tool execution emits EMF metrics: ToolExecutionDuration, ToolSuccessRate, ToolErrorRate |
| **Testability** | Mock tool executors for unit/integration tests; tool stubs for E2E tests |
| **Configurability** | Tools enabled via environment variables or SSM parameters |
| **Documentation** | Each tool has documented parameters, return schema, and error codes |

---

## 4. Implementation Scope & Phasing

### 4.1 MVP Scope (Phase 1)

**Goal**: Demonstrate tool calling works end-to-end with one real tool.

**In Scope**:
- Tool registry with declarative tool definitions
- Single tool execution (sequential only)
- Basic timeout handling
- Error messages for users
- Audit logging to CloudWatch
- 2-3 example tools:
  - `echo_tool` (testing only - returns input)
  - `get_current_time` (simple, no external deps)
  - `transfer_to_agent` (signals escalation, no actual transfer)

**Out of Scope**:
- Parallel tool execution
- Tool chaining (multiple sequential calls)
- External API integrations (CRM, order system)
- Tool confirmation dialogs
- Advanced retry strategies
- conversational-delay-handling integration (parallel track)

**Estimated Effort**: 2-3 weeks

### 4.2 Phase 2: Production Tools

**Goal**: Real business value with customer-facing tools.

**In Scope**:
- `get_customer_info` - DynamoDB or CRM lookup
- `check_order_status` - Order management system
- `create_support_ticket` - Ticket creation (with confirmation)
- conversational-delay-handling integration
- Parallel tool execution
- Circuit breaker for external APIs
- PII redaction in logs

**Estimated Effort**: 3-4 weeks

### 4.3 Phase 3: Advanced Features

**Goal**: Enterprise-ready tool framework.

**In Scope**:
- Tool chaining with state management
- Role-based tool access control
- Tool analytics dashboard
- A/B testing for tool prompts
- knowledge-base-rag as a tool
- Custom tool development guide

**Estimated Effort**: 4-6 weeks

### 4.4 Value vs Effort Matrix

```
                    HIGH VALUE
                        │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
    │   Quick Wins      │   Major Projects  │
    │   ───────────     │   ──────────────  │
    │   - echo_tool     │   - get_customer  │
    │   - get_time      │   - order_status  │
    │   - transfer      │   - create_ticket │
    │                   │   - parallel exec │
LOW ├───────────────────┼───────────────────┤ HIGH
EFFORT                  │                   EFFORT
    │   Fill-ins        │   Avoid (for now) │
    │   ────────        │   ──────────────  │
    │   - tool metrics  │   - tool chaining │
    │   - audit logs    │   - RBAC          │
    │                   │   - A/B testing   │
    │                   │                   │
    └───────────────────┼───────────────────┘
                        │
                    LOW VALUE
```

---

## 5. Related Feature Integration

### 5.1 Integration with conversational-delay-handling

**Relationship**: Hard dependency for production use.

**Integration Points**:

1. **Delay Detection Hook**
   ```python
   # Tool executor should emit event when starting
   async def execute_tool(tool_call):
       emit_event("tool_execution_started", tool_name=tool_call.name)
       # conversational-delay-handling listens and starts 1.5s timer
       result = await tool.executor(tool_call.params)
       emit_event("tool_execution_completed")
       return result
   ```

2. **Contextual Filler Phrases**
   ```python
   TOOL_FILLERS = {
       "get_customer_info": "Let me pull up your account...",
       "check_order_status": "I'm checking on that order for you...",
       "create_support_ticket": "I'm creating a support ticket now...",
       "default": "Just a moment while I look that up...",
   }
   ```

3. **Cancellation Coordination**
   - If user barges in during filler, cancel both filler AND tool execution
   - Tool executor must support cancellation via `asyncio.CancelledError`

**Recommended Approach**: Implement tool-calling-framework first with stub delay handling, then integrate conversational-delay-handling in Phase 2.

### 5.2 Integration with knowledge-base-rag

**Relationship**: RAG can be implemented as a tool.

**Architecture Options**:

| Option | Pros | Cons |
|--------|------|------|
| **RAG as Tool** | Consistent pattern; LLM decides when to search | Extra LLM round-trip; higher latency |
| **RAG as Pipeline Stage** | Lower latency; always-on context | Less flexible; may retrieve irrelevant info |
| **Hybrid** | Best of both; RAG for known intents, tool for explicit search | Complexity |

**Recommendation**: Start with RAG as Pipeline Stage (lower latency), add explicit `search_knowledge_base` tool for user-requested searches.

```python
# Example: RAG as a tool
@register_tool(
    name="search_knowledge_base",
    description="Search company knowledge base for policies, FAQs, and procedures",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"]
    }
)
async def search_kb(query: str, context: SessionContext) -> dict:
    results = await bedrock_kb.retrieve(query, max_results=3)
    return {
        "results": [
            {"title": r.title, "content": r.content[:500]}
            for r in results
        ]
    }
```

---

## 6. Technical Architecture Recommendation

### 6.1 Proposed Component Structure

```
backend/voice-agent/app/
├── tools/
│   ├── __init__.py
│   ├── registry.py          # ToolRegistry class
│   ├── executor.py          # ToolExecutor with timeout/retry
│   ├── schemas.py           # Pydantic models for tool definitions
│   ├── decorators.py        # @register_tool decorator
│   └── builtin/
│       ├── __init__.py
│       ├── echo_tool.py     # Testing tool
│       ├── time_tool.py     # Current time
│       └── transfer_tool.py # Agent escalation
├── services/
│   └── bedrock_llm_tools.py # Extended AWSBedrockLLMService with tool support
└── observability.py         # (existing) Add ToolExecutionObserver
```

### 6.2 Key Interfaces

```python
# Tool Definition
@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema
    executor: Callable[[dict, SessionContext], Awaitable[dict]]
    timeout_seconds: float = 5.0
    requires_confirmation: bool = False

# Tool Registry
class ToolRegistry:
    def register(self, tool: ToolDefinition) -> None: ...
    def get(self, name: str) -> ToolDefinition: ...
    def list_tools(self) -> List[ToolDefinition]: ...
    def to_bedrock_format(self) -> List[dict]: ...  # For toolConfig

# Tool Executor
class ToolExecutor:
    async def execute(
        self,
        tool_call: ToolUseBlock,
        context: SessionContext,
    ) -> ToolResultBlock: ...
```

### 6.3 Pipeline Integration

```python
# In pipeline_ecs.py (conceptual)
async def create_voice_pipeline(config, collector):
    # ... existing setup ...

    # Register tools
    tool_registry = ToolRegistry()
    tool_registry.register(echo_tool)
    tool_registry.register(time_tool)
    tool_registry.register(transfer_tool)

    # Create LLM with tools
    llm = AWSBedrockLLMService(
        model="us.anthropic.claude-3-5-haiku-20241022-v1:0",
        region=config.aws_region,
        # Pipecat's built-in tool support
        tools=tool_registry.to_bedrock_format(),
    )

    # Register tool executors
    for tool in tool_registry.list_tools():
        llm.register_function(tool.name, tool.executor)

    # ... rest of pipeline ...
```

---

## 7. Success Metrics

### 7.1 Launch Criteria (MVP)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Tool invocation success rate | >95% | (successful_calls / total_calls) |
| Tool-related user complaints | 0 critical bugs | Support tickets |
| E2E latency with tool | <3s P95 | CloudWatch E2ELatency with tool_used=true |
| Tool timeout rate | <5% | CloudWatch ToolTimeoutCount |

### 7.2 Ongoing KPIs

| KPI | Description | Target |
|-----|-------------|--------|
| **Tool Adoption** | % of conversations using tools | >30% (indicates value) |
| **Tool Success Rate** | Tools returning valid results | >90% |
| **Mean Tool Latency** | Average tool execution time | <1000ms |
| **User Satisfaction Delta** | NPS change after tool launch | +5 points |

---

## 8. Open Questions for Stakeholders

1. **Tool Access Control**: Should all tools be available to all callers, or do we need role-based access?

2. **Confirmation UX**: For destructive actions (create ticket), what's the confirmation flow?
   - Option A: "I'll create a ticket. Is that okay?" (verbal confirmation)
   - Option B: Immediate creation with "I've created ticket #123"

3. **Tool Latency Budget**: What's the maximum acceptable E2E latency for tool-using turns?
   - Current: ~700ms without tools
   - Proposed: <3000ms with tools (4x increase)

4. **Audit Retention**: How long should tool execution logs be retained for compliance?

5. **External API Ownership**: Who owns the SLA for external APIs (CRM, order system)?

---

## 9. Appendices

### Appendix A: Bedrock Converse API Tool Use Flow

```
┌─────────────┐                          ┌─────────────┐
│   Pipeline  │                          │   Bedrock   │
└──────┬──────┘                          └──────┬──────┘
       │                                        │
       │  1. Converse(messages, toolConfig)     │
       │───────────────────────────────────────►│
       │                                        │
       │  2. stopReason: "tool_use"             │
       │     content: [toolUse: {...}]          │
       │◄───────────────────────────────────────│
       │                                        │
       │  3. Execute tool locally               │
       │─────┐                                  │
       │     │                                  │
       │◄────┘                                  │
       │                                        │
       │  4. Converse(messages + toolResult)    │
       │───────────────────────────────────────►│
       │                                        │
       │  5. stopReason: "end_turn"             │
       │     content: [text: "..."]             │
       │◄───────────────────────────────────────│
       │                                        │
```

### Appendix B: Example Tool Definition

```python
from app.tools import register_tool, ToolContext

@register_tool(
    name="get_order_status",
    description="Look up the status of a customer order by order ID or phone number",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {
                "type": "string",
                "description": "The order ID (e.g., ORD-12345)"
            },
            "phone_number": {
                "type": "string",
                "description": "Customer phone number to look up recent orders"
            }
        },
        "oneOf": [
            {"required": ["order_id"]},
            {"required": ["phone_number"]}
        ]
    },
    timeout_seconds=5.0
)
async def get_order_status(
    context: ToolContext,
    order_id: str = None,
    phone_number: str = None
) -> dict:
    """
    Returns order status for the given order ID or phone number.
    """
    if order_id:
        order = await order_service.get_by_id(order_id)
    else:
        orders = await order_service.get_by_phone(phone_number)
        order = orders[0] if orders else None

    if not order:
        return {"status": "not_found", "message": "No order found"}

    return {
        "status": "found",
        "order_id": order.id,
        "order_status": order.status,
        "estimated_delivery": order.estimated_delivery,
        "items": [item.name for item in order.items[:3]]  # Limit for context
    }
```

### Appendix C: Related Documentation

- [Pipecat Function Calling Guide](https://docs.pipecat.ai/guides/learn/function-calling)
- [AWS Bedrock Tool Use Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html)
- [Bedrock Converse API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)
- [Pipecat AWSBedrockLLMService API](https://reference-server.pipecat.ai/en/stable/api/pipecat.services.aws.llm.html)

---

## Document Approval

| Role | Name | Date | Status |
|------|------|------|--------|
| Product Manager | | | Pending |
| Tech Lead | | | Pending |
| Security Review | | | Pending |
| QA Lead | | | Pending |

---

**Next Steps**:
1. Review with stakeholders
2. Resolve open questions
3. Create implementation plan document
4. Begin MVP implementation
