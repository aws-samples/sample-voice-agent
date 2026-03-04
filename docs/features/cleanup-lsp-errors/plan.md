---
started: 2026-02-11
---

# Implementation Plan: Cleanup LSP Type Errors in Pipeline

## Overview
Fix LSP (Language Server Protocol) type errors in `pipeline_ecs.py` that are causing IDE warnings. These type mismatches indicate potential bugs and reduce code maintainability.

## Current State

### Type Errors to Fix
1. **Line 156**: DailyTransport api_key expects `str` but receives `str | None`
2. **Line 268**: OpenAILLMContext messages type mismatch (`list[dict[str, str]]` vs expected OpenAI types)
3. **Line 268**: OpenAILLMContext tools type mismatch (`List[Dict[str, Any]] | None` vs expected tool types)

### Additional Issues Discovered
4. **Lines 339, 343, 347, 351, 356, 366**: Observer list typed as `List[MetricsObserver]` instead of `List[BaseObserver]`

## Implementation Steps

### Phase 1: Core Type Fixes

- [ ] **Step 1**: Add required imports
  - Import `ChatCompletionSystemMessageParam` from `openai.types.chat`
  - Import `NOT_GIVEN` from `openai._types`
  - Import `BaseObserver` from `pipecat.processors.base_observer`

- [ ] **Step 2**: Fix DailyParams api_key (Line 156)
  - Add null check for `DAILY_API_KEY` environment variable
  - Raise `ValueError` with descriptive message if missing
  - Ensure api_key is guaranteed to be `str` when passed to DailyParams

- [ ] **Step 3**: Fix OpenAILLMContext messages (Line 268)
  - Convert plain dict messages to `ChatCompletionSystemMessageParam` type
  - Update type annotation for messages variable

- [ ] **Step 4**: Fix OpenAILLMContext tools (Line 268)
  - Use `NOT_GIVEN` for tools parameter when passing Bedrock-format tools
  - Document why Bedrock tools aren't converted for OpenAI context

### Phase 2: Observer Type Fixes

- [ ] **Step 5**: Fix observer list types
  - Change observer list type from `List[MetricsObserver]` to `List[BaseObserver]`
  - Verify all observer implementations inherit from BaseObserver

### Phase 3: Validation

- [ ] **Step 6**: Run type checking
  - Execute mypy on pipeline_ecs.py
  - Verify no type errors on lines 156, 268, or observer lines

- [ ] **Step 7**: Runtime testing
  - Test pipeline creation with valid DAILY_API_KEY
  - Verify error handling when DAILY_API_KEY is missing
  - Ensure no runtime regressions in pipeline functionality

## Technical Decisions

### Tools Parameter Handling
**Decision**: Use `NOT_GIVEN` instead of converting Bedrock tools to OpenAI format.

**Rationale**: 
- The tools are in Bedrock format and used by Bedrock LLM, not OpenAI
- OpenAILLMContext is used for context management, not tool execution
- Converting tool formats would add unnecessary complexity
- Using `NOT_GIVEN` is the idiomatic way to indicate "no value" in OpenAI SDK

### Message Type Conversion
**Decision**: Use `ChatCompletionSystemMessageParam` for system messages.

**Rationale**:
- Properly typed message parameters provide IDE autocomplete
- Matches OpenAI SDK's expected types
- Enables better type checking for message content

## Testing Strategy

### Type Checking
```bash
cd backend/voice-agent
.venv/bin/python -m mypy app/pipeline_ecs.py --no-error-summary
```

### Runtime Tests
1. **Valid API key scenario**: Pipeline creates successfully
2. **Missing API key scenario**: Raises ValueError with clear message
3. **Message context**: OpenAILLMContext accepts properly typed messages
4. **Observer registration**: All observers attach without type errors

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Runtime regression from type changes | Medium | Thorough testing, incremental changes |
| Import errors from new dependencies | Low | Verify imports exist in current environment |
| Breaking change to observer interfaces | Low | Verify BaseObserver is parent of all observers |

## Success Criteria

- [ ] Zero mypy errors on targeted lines (156, 268, observer lines)
- [ ] No runtime regressions in pipeline functionality
- [ ] Clear error message when DAILY_API_KEY is missing
- [ ] IDE shows no type warnings on fixed code

## Notes

- These are type-checking fixes only - runtime behavior should remain unchanged
- Using proper type hints from pipecat's type definitions
- Consider using `typing.cast()` only if type narrowing is insufficient
