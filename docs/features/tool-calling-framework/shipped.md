---
shipped: 2026-01-27
---

# Shipped: Tool Calling Framework

## Summary

Implemented a comprehensive tool calling framework that enables the voice agent to execute real actions during conversations. The framework integrates with AWS Bedrock's Converse API and Pipecat's function calling system to provide declarative tool registration, safe async execution with timeouts, comprehensive error handling, and full observability integration.

## Key Changes

- Created `backend/voice-agent/app/tools/` module with registry, executor, schemas, context, and result classes
- Implemented Bedrock-native tool spec format (`toolSpec` with `inputSchema`) for compatibility with Converse API
- Added three built-in tools: `echo` (testing), `get_current_time`, and `transfer_to_agent`
- Integrated tool execution with CloudWatch EMF metrics (ToolExecutionTime, ToolInvocationCount)
- Added pipeline integration in `pipeline_ecs.py` with `ENABLE_TOOL_CALLING` environment variable
- Created comprehensive test suite: 79 tool-related tests with 93% code coverage

## Testing

- **Unit Tests**: 79 tests covering registry, executor, schemas, and integration
- **Full Suite**: 215 backend tests + 71 infrastructure tests passing
- **Manual Testing**: Deployed and verified with live voice call asking "what time is it?"
- **Security Review**: No Critical/High issues found; 1 Medium (error message sanitization) and 3 Low recommendations

## Notes

- Tool calling is opt-in via `ENABLE_TOOL_CALLING=true` environment variable (defaults to false)
- Phase 2 features (external API tools, circuit breakers, parallel execution) are tracked in the plan for future implementation
- Security recommendation to sanitize exception messages before returning in ToolResult should be addressed in follow-up
