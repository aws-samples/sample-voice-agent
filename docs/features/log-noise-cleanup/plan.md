---
name: Log Noise Cleanup
status: completed
created: 2026-02-27
updated: 2026-02-27
---

# Log Noise Cleanup -- Implementation Plan

## Status: Completed

All phases shipped and verified via SIPp test call. CloudWatch logs are 100% structured JSON with zero deprecation warnings and zero pipecat loguru DEBUG noise.

### Results (before vs after)

| Metric | Before | After |
|--------|--------|-------|
| Deprecation warnings per call | ~8 | 0 |
| Pipecat loguru DEBUG lines per call | ~48 | 0 |
| Structured JSON ratio | ~60% | 100% |
| Non-JSON log lines per call | ~56 | 0 (excluding aiohttp session warnings) |

## Overview

Eliminate four categories of log noise from the voice agent's CloudWatch log stream so that structured JSON logs from our code are not polluted by unstructured third-party output. The work was completed in two phases plus targeted suppressions for pipecat-internal issues.

## Codebase Investigation Summary

| Finding | Location | Detail |
|---------|----------|--------|
| No pipecat logger level config | Entire codebase | Pipecat DEBUG logs appear whenever basicConfig runs |
| Deprecated: `OpenAILLMContext` | `pipeline_ecs.py:39,399` | Should be `LLMContext` + `LLMContextAggregatorPair` |
| Deprecated: `ai_services` import | `bedrock_llm.py:25` | Dead code -- `BedrockLLMService` is never used by active pipeline |
| Deprecated: `vad_enabled` param | `pipeline_ecs.py:245` | Redundant when `vad_analyzer` already provided |
| Deprecated: 6-param handler sig | `pipeline_ecs.py:707`, `tool_adapter.py:72`, `executor.py:249` | Should use single `FunctionCallParams` parameter |
| Deprecated: `vad_audio_passthrough` | `pipeline_ecs.py:254` | Passthrough is now always enabled by default |
| Deprecated: `vad_analyzer` on DailyParams | `pipeline_ecs.py:249` | Moved to `LLMUserAggregatorParams` in v0.0.101 |
| Deprecated: `LLMMessagesFrame` | `pipeline_ecs.py:542` | Replaced by `LLMMessagesUpdateFrame` with `run_llm=True` |
| Pipecat uses loguru (not stdlib) | Internal | `logging.getLogger("pipecat").setLevel(WARNING)` doesn't suppress loguru |
| No RTVI / `send_message` usage | Entire codebase | Daily transport error originates inside pipecat internals |
| Two entrypoints | `service_main.py`, `ecs_main.py` | Both need pipecat logger level treatment |

### New APIs Verified in pipecat v0.0.102

All replacement APIs exist and are importable:

| Class | Import Path |
|-------|-------------|
| `LLMContext` | `pipecat.processors.aggregators.llm_context` |
| `LLMContextAggregatorPair` | `pipecat.processors.aggregators.llm_response_universal` |
| `LLMUserAggregatorParams` | `pipecat.processors.aggregators.llm_response_universal` |
| `FunctionCallParams` | `pipecat.services.llm_service` |
| `ToolsSchema` | `pipecat.adapters.schemas.tools_schema` |
| `FunctionSchema` | `pipecat.adapters.schemas.function_schema` |
| `LLMMessagesUpdateFrame` | `pipecat.frames.frames` |

## Phase 1: Quick Wins -- COMPLETED

### Step 1.1: Suppress Pipecat DEBUG Logs

**Files:** `service_main.py`, `ecs_main.py`

Added `logging.getLogger("pipecat").setLevel(logging.WARNING)` and `loguru.logger.disable("pipecat")` to suppress both stdlib and loguru-based pipecat DEBUG output.

### Step 1.2: Remove Dead Code (`BedrockLLMService`)

Deleted `app/services/bedrock_llm.py` and removed re-export from `app/services/__init__.py`. Eliminated `pipecat.services.ai_services` deprecation warning.

### Step 1.3: Remove Redundant `vad_enabled` Parameter

Removed `vad_enabled=True` from `pipeline_ecs.py` DailyParams.

## Phase 2: Pipecat API Migration -- COMPLETED

### Step 2.1: Migrate `OpenAILLMContext` to `LLMContext`

Migrated from `OpenAILLMContext` + `llm.create_context_aggregator()` to `LLMContext` + `LLMContextAggregatorPair` + `ToolsSchema` in `pipeline_ecs.py`. Added `to_function_schema()` method to `ToolDefinition`.

### Step 2.2: Migrate Handler Signatures to `FunctionCallParams`

Updated all 3 handler functions (`pipeline_ecs.py`, `tool_adapter.py`, `executor.py`) to accept single `FunctionCallParams` parameter.

### Step 2.3: Remove `vad_audio_passthrough` and Migrate `vad_analyzer`

Removed deprecated `vad_audio_passthrough=True` from DailyParams (passthrough is always enabled by default). Moved `vad_analyzer` from DailyParams to `LLMUserAggregatorParams` as required by pipecat v0.0.101+.

### Step 2.4: Replace `LLMMessagesFrame` with `LLMMessagesUpdateFrame`

Replaced `LLMMessagesFrame(messages)` with `LLMMessagesUpdateFrame(messages, run_llm=True)` for the greeting trigger in `on_first_participant_joined`.

### Step 2.5: Clean Up Stale References

Updated docstrings, removed unused imports (`ChatCompletionMessageParam` unused import, `OpenAILLMContext` references in registry docstrings).

## Phase 3: Targeted Suppressions for Pipecat-Internal Issues -- COMPLETED

Two deprecation warnings originate inside pipecat's own code and cannot be fixed at source in our codebase:

### 3.1: `OpenAILLMContext` Deprecation (Bedrock Adapter Internal)

Pipecat's `AWSBedrockLLMService` internally calls `AWSBedrockLLMContext.upgrade_to_bedrock()` which creates a class inheriting from deprecated `OpenAILLMContext`. Our code passes `LLMContext` but pipecat upgrades it internally.

**Suppression:** `warnings.filterwarnings("ignore", message=r"OpenAILLMContext is deprecated", ...)` in both entrypoints.

### 3.2: `DeprecatedModuleProxy` for Deepgram Module

Pipecat's `pipecat.services.deepgram.__init__.py` installs a `DeprecatedModuleProxy` that fires even when importing from correct sub-module paths (`pipecat.services.deepgram.stt_sagemaker`). The proxy uses `warnings.simplefilter("always")` inside a `catch_warnings` context, defeating any `filterwarnings()` calls.

**Suppression:** Pre-seed `pipecat.services._warned_modules` with `("deepgram", "deepgram.[stt,tts]")` before the import occurs, preventing the warning from ever being emitted.

## Files Modified

### Source files
- `app/service_main.py` -- pipecat logger levels, loguru disable, warnings filters, _warned_modules pre-seed
- `app/ecs_main.py` -- same as service_main.py
- `app/pipeline_ecs.py` -- LLMContext, LLMContextAggregatorPair, LLMUserAggregatorParams, FunctionCallParams, LLMMessagesUpdateFrame, ToolsSchema, removed vad_audio_passthrough/vad_analyzer from DailyParams
- `app/tools/schema.py` -- added `to_function_schema()` and `_build_properties_and_required()`
- `app/a2a/tool_adapter.py` -- FunctionCallParams migration
- `app/a2a/registry.py` -- docstring update
- `app/tools/executor.py` -- FunctionCallParams migration in `create_pipecat_wrapper`
- `app/services/__init__.py` -- removed BedrockLLMService re-export

### Deleted files
- `app/services/bedrock_llm.py` -- dead code

### Test files
- `tests/test_a2a_tool_adapter.py` -- FunctionCallParams mock helper
- `tests/test_a2a_pipeline_integration.py` -- FunctionSchema mocks
- `tests/test_tool_integration.py` -- FunctionCallParams mock
- `tests/test_capabilities.py` -- test_returns_function_schema_tool_specs
- `tests/test_auto_scaling_integration.py` -- fixed pre-existing "error"->"rejected" bug

## Out of Scope

| Issue | Reason |
|-------|--------|
| Observer event spam (11x duplicate events) | Tracked in `fix-observer-event-spam` |
| AWS CRT BiDi teardown race | Tracked in `fix-aws-crt-bidi-teardown-race` |
| Per-audio-frame chatty events | Related to `fix-observer-event-spam` |
| Pipecat major version upgrade | Separate effort |
| Unifying `service_main.py` / `ecs_main.py` structlog config | Different scope |
| Unclosed aiohttp client session warnings | Minor cleanup, not deprecation-related |
