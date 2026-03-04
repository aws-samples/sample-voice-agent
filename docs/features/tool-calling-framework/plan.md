---
started: 2026-01-27
---

# Implementation Plan: Tool Calling Framework

## Overview

This plan implements a comprehensive tool calling framework that enables the voice agent to execute real actions during conversations. The framework leverages Pipecat's built-in `AWSBedrockLLMService.register_function()` capability and adds type-safe tool registration, async execution with timeouts, comprehensive error handling, and full observability integration.

## Architecture Summary

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│ ToolRegistry│────▶│ ToolExecutor │────▶│ External API │────▶│ ToolResult  │
│ (startup)   │     │ (timeout)    │     │ (or local)   │     │ (formatted) │
└─────────────┘     └──────────────┘     └──────────────┘     └─────────────┘
       │                   │                                         │
       ▼                   ▼                                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Pipecat Pipeline (LLM with toolConfig)               │
│  STT → Context → LLM → [Tool Execution] → LLM (synthesis) → TTS        │
└─────────────────────────────────────────────────────────────────────────┘
       │                   │                                         │
       ▼                   ▼                                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Observability (CloudWatch EMF)                    │
│  ToolExecutionTime | ToolInvocationCount | ToolErrorRate | ToolTimeout │
└─────────────────────────────────────────────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Core Framework (MVP)

- [x] Step 1: Create tools module structure
  - Create `backend/voice-agent/app/tools/` directory
  - Create `__init__.py` with public exports
  - Set up module structure for registry, executor, schemas

- [x] Step 2: Implement ToolDefinition and schemas
  - Create `schema.py` with ToolDefinition, ToolParameter, ToolCategory
  - Implement `to_bedrock_tool_spec()` conversion method
  - Add JSON schema validation for parameters

- [x] Step 3: Implement ToolRegistry
  - Create `registry.py` with ToolRegistry class
  - Add registration with validation
  - Add `get_bedrock_tool_config()` for Pipecat integration
  - Add global registry singleton pattern

- [x] Step 4: Implement ToolContext and ToolResult
  - Create `context.py` with session context for executors
  - Create `result.py` with ToolResult, ToolStatus enum
  - Implement `to_bedrock_tool_result()` conversion
  - Add user-facing error message generation

- [x] Step 5: Implement ToolExecutor
  - Create `executor.py` with async execution
  - Add configurable timeout per tool (asyncio.wait_for)
  - Add exception handling with structured errors
  - Add cancellation support for barge-in scenarios

- [x] Step 6: Pipeline integration
  - Modify `pipeline_ecs.py` to register tools with LLM
  - Create wrapper functions adapting executor to Pipecat's signature
  - Add tool configuration to LLM service initialization

- [x] Step 7: Add observability integration
  - Extend MetricsCollector with `record_tool_execution()`
  - Add EMF metrics for tool execution (duration, status, category)
  - Create ToolUseObserver for audit logging

- [x] Step 8: Implement example tools
  - Create `builtin/` subdirectory
  - Implement `echo_tool` for testing
  - Implement `get_current_time` (no external deps)
  - Implement `transfer_to_agent` (signals escalation)

- [x] Step 9: Add unit tests
  - Test ToolRegistry registration and validation
  - Test ToolExecutor timeout and error handling
  - Test Bedrock format conversion
  - Test tool wrapper integration

- [x] Step 10: Add integration tests
  - Test end-to-end tool call flow with mock LLM
  - Test barge-in cancellation
  - Test multiple tool calls in sequence

### Phase 2: Production Tools (Future)

- [ ] Implement `get_customer_info` tool with DynamoDB
- [ ] Implement `check_order_status` tool
- [ ] Implement `create_support_ticket` tool with confirmation
- [ ] Add integration with `conversational-delay-handling`
- [ ] Add parallel tool execution support
- [ ] Add circuit breaker for external APIs

## Technical Decisions

### 1. Leverage Pipecat's Built-in Function Calling
Rather than implementing custom Bedrock Converse API handling, we use Pipecat's `AWSBedrockLLMService.register_function()` which:
- Automatically formats tool definitions for Bedrock's `toolConfig`
- Handles tool_use parsing and result formatting
- Manages the LLM re-invocation loop

### 2. Separate Tool Definition from Execution
ToolDefinition contains metadata + executor reference, allowing:
- Declarative tool registration at startup
- Easy testing with mock executors
- Clear separation of concerns

### 3. Context-Based Execution
ToolContext provides executors with:
- Session/call identifiers for audit
- Metrics collector for observability
- Cancellation signal for barge-in support
- User identity for authorization checks

### 4. Structured Error Handling
All errors converted to ToolResult with:
- Status enum (SUCCESS, ERROR, TIMEOUT, CANCELLED)
- Error code for categorization
- User-friendly message for TTS fallback

## Testing Strategy

### Unit Tests
- `test_tool_registry.py`: Registration, validation, Bedrock format conversion
- `test_tool_executor.py`: Timeout handling, error recovery, cancellation
- `test_tool_schemas.py`: JSON schema validation, ToolResult formatting

### Integration Tests
- `test_pipeline_tools.py`: End-to-end with mock LLM service
- `test_tool_observers.py`: Metrics collection and audit logging

### Manual Testing
- Deploy to dev environment
- Test with real voice calls
- Verify CloudWatch metrics appear correctly

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Latency increase from tool calls | High - poor UX | Hard limit on tool timeout; filler phrase integration in Phase 2 |
| Tool execution failures | Medium - broken features | Graceful error messages; LLM synthesizes fallback response |
| Pipecat function calling incompatibility | High - rework needed | Verify with minimal POC before full implementation |
| External API instability | Medium - partial failures | Circuit breaker pattern in Phase 2 |

## Dependencies

- **Pipecat v0.0.100+**: Requires `AWSBedrockLLMService` with function calling support
- **conversational-delay-handling**: Soft dependency for filler phrases (Phase 2)
- **External APIs**: Soft dependency for production tools (Phase 2)

## File Structure

```
backend/voice-agent/app/tools/
├── __init__.py           # Public exports
├── schema.py             # ToolDefinition, ToolParameter, ToolCategory
├── registry.py           # ToolRegistry, get_global_registry()
├── executor.py           # ToolExecutor with timeout/retry
├── context.py            # ToolContext for session info
├── result.py             # ToolResult, ToolStatus
└── builtin/
    ├── __init__.py       # Built-in tool exports
    ├── echo_tool.py      # Testing tool
    ├── time_tool.py      # get_current_time
    └── transfer_tool.py  # transfer_to_agent

backend/voice-agent/tests/
├── test_tool_registry.py
├── test_tool_executor.py
└── test_tool_schemas.py
```

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Tool invocation success rate | >95% | CloudWatch ToolInvocationCount by status |
| Tool execution P50 latency | <1000ms | CloudWatch ToolExecutionTime |
| Tool timeout rate | <5% | CloudWatch ToolTimeoutCount |
| Test coverage | >80% | pytest-cov report |

## Progress Log

| Date | Update |
|------|--------|
| 2026-01-27 | Plan created, requirements analysis complete, API design complete |
| 2026-01-27 | MVP implementation complete (Steps 1-9): tool framework, registry, executor, builtin tools, observability, pipeline integration, 60 unit tests passing |
| 2026-01-27 | Integration tests complete (Step 10): 19 integration tests added, 215 total tests passing |
