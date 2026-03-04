---
shipped: 2026-01-28
---

# Shipped: Conversational Delay Handling

## Summary

Implemented filler phrase system for tool execution delays, plus replaced the echo tool with a random number tool that works reliably with the LLM.

## Key Changes

- **FunctionCallFillerProcessor**: Pipeline processor that intercepts `FunctionCallsStartedFrame` and injects contextual filler phrases (e.g., "Let me look that up for you...") before tool execution
- **random_number_tool**: New tool that generates random numbers - works reliably because the LLM must speak the result to answer the user's question
- **slow_random_tool**: 2-second delay version for testing filler phrase behavior
- **ENABLE_FILLER_PHRASES config**: Environment variable to enable/disable fillers (disabled by default)

## Technical Decisions

- **Fillers disabled by default**: The LLM naturally generates pre-tool text ("I'll help you with that..."), making additional fillers redundant. Can be enabled via `ENABLE_FILLER_PHRASES=true`.
- **Replaced echo tool with random_number**: The echo tool failed because the LLM thought "echoing" happened inside the tool. Random number works because the LLM must speak to answer "what number did you pick?"

## Testing

- 246 unit/integration tests passing
- Manual testing verified:
  - "Give me a random number" → Tool returns 34 → LLM says "Your random number is 34"
  - "Slowly pick a random number" → With fillers enabled, speaks "I'm looking into that now..." during 2s delay, then speaks the number
- Deployed and tested in production ECS environment

## Files Added/Modified

- `backend/voice-agent/app/function_call_filler_processor.py` - New filler processor
- `backend/voice-agent/app/filler_phrases.py` - Phrase management (legacy)
- `backend/voice-agent/app/tools/builtin/random_number_tool.py` - New random number tool
- `backend/voice-agent/app/tools/builtin/slow_random_tool.py` - Delayed version for testing
- `backend/voice-agent/app/pipeline_ecs.py` - Integrated filler processor and new tools
- `infrastructure/src/stacks/ecs-stack.ts` - Added ENABLE_FILLER_PHRASES config

## Notes

- Filler phrases are disabled by default because LLM pre-tool text serves the same purpose
- To enable fillers, set `ENABLE_FILLER_PHRASES=true` in the ECS task definition
- The slow_random_tool is useful for testing delays but should be removed in production
