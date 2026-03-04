---
id: cleanup-lsp-errors
name: Cleanup LSP Type Errors in Pipeline
type: Tech Debt
priority: P2
effort: Small
impact: Low
created: 2026-02-11
---

# Cleanup LSP Type Errors in Pipeline

## Problem Statement

The `pipeline_ecs.py` file has several LSP (Language Server Protocol) type errors that are causing warnings in the IDE. While these don't affect runtime functionality, they indicate type mismatches that could lead to bugs and make the code harder to maintain.

## Current Errors

1. **Line 156**: `Argument of type "str | None" cannot be assigned to parameter "api_key" of type "str"`
   - DailyTransport api_key parameter expects str but receives str | None

2. **Line 268**: `Argument of type "list[dict[str, str]]" cannot be assigned to parameter "messages"`
   - OpenAILLMContext messages parameter type mismatch

3. **Line 268**: `Argument of type "List[Dict[str, Any]] | None" cannot be assigned to parameter "tools"`
   - Tools parameter type mismatch in LLM context

## Proposed Solution

1. Add proper type assertions or null checks for the api_key
2. Update the messages list to use proper ChatCompletionMessageParam types
3. Fix the tools list typing to match expected ChatCompletionToolParam type

## Affected Areas
- `/backend/voice-agent/app/pipeline_ecs.py`

## Notes
- These are type-checking issues only - runtime works fine
- Should use proper type hints from pipecat's type definitions
- Consider using `typing.cast()` or proper type narrowing
