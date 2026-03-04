---
name: Log Noise Cleanup
type: tech-debt
priority: P2
effort: medium
impact: medium
status: idea
created: 2026-02-26
related-to: log-analysis, fix-observer-event-spam, fix-aws-crt-bidi-teardown-race
depends-on: []
---

# Log Noise Cleanup

## Problem Statement

After completing the log-analysis feature (structured logging, error_type, call_id propagation, access log suppression), a review of CloudWatch logs from a live SIPp call revealed four remaining categories of log noise that pollute the structured JSON log stream. These are all third-party or framework-level issues that our code doesn't control directly, but they degrade log quality and make CloudWatch Insights queries harder to use.

Observed in log stream `voice-agent/voice-agent/d508ec2e86ac48e9be6cdcf506ba4583` during a SIPp call on 2026-02-26.

## Issue Categories

### 1. Unstructured Pipecat Debug Logs

Pipecat's internal modules use stdlib `logging` with a pipe-delimited format that doesn't match our structlog JSON convention:

```
2026-02-26 23:23:53.838 | DEBUG | pipecat.processors.metrics.frame_processor_metrics:stop_processing_metrics:152 - AWSBedrockLLMService#0 processing time: 0.5015373229980469
2026-02-26 23:23:53.839 | DEBUG | pipecat.processors.metrics.frame_processor_metrics:stop_ttfb_metrics:131 - AWSBedrockLLMService#0 TTFB: 0.5018789768218994
2026-02-26 23:15:34.466 | DEBUG | pipecat.processors.frame_processor:link:561 - Linking Pipeline#0::Source -> DailyInputTransport#0
2026-02-26 23:15:34.465 | DEBUG | pipecat.audio.vad.silero:__init__:147 - Loading Silero VAD model...
```

**Volume:** ~50-100+ lines per call depending on conversation length.

**Root cause:** `service_main.py` sets `logging.basicConfig(level=logging.INFO)` as a safety net for non-structlog modules, but Pipecat configures its own loggers at DEBUG level internally.

**Proposed fix:**
- Option A: Set pipecat's root logger to WARNING/INFO: `logging.getLogger("pipecat").setLevel(logging.WARNING)` -- suppresses debug-level pipe-format logs while keeping errors visible.
- Option B: Route pipecat logs through structlog via a `ProcessorFormatter` bridge so they render as JSON with the same timestamp/event format.
- Option C: Set `LOG_LEVEL=INFO` or `WARNING` for pipecat-specific loggers after import.

**Recommendation:** Option A for immediate noise reduction; Option B as a follow-up if pipecat logs contain operationally useful info at INFO level.

### 2. Python DeprecationWarnings

Python `DeprecationWarning` messages from Pipecat appear as bare unstructured text in the log stream:

```
<string>:4: DeprecationWarning: OpenAILLMContextFrame is deprecated and will be removed in a future version. Use LLMContextFrame with the universal `LLMContext` and `LLMContextAggregatorPair` instead. See OpenAILLMContext docstring for migration guide.

/app/venv/lib/python3.12/site-packages/pipecat/services/llm_service.py:533: DeprecationWarning: Function calls with parameters `(function_name, tool_call_id, arguments, llm, context, result_callback)` are deprecated, use a single `FunctionCallParams` parameter instead.
  warnings.warn(

/app/venv/lib/python3.12/site-packages/pipecat/transports/base_input.py:101: DeprecationWarning: Parameter 'vad_enabled' is deprecated, use 'audio_in_enabled' and 'vad_analyzer' instead.

/app/app/services/bedrock_llm.py:25: DeprecationWarning: Module `pipecat.services.ai_services` is deprecated, use `pipecat.services.[ai_service,image_service,llm_service,stt_service,tts_service,vision_service]` instead.

/app/app/services/factory.py:43: DeprecationWarning: Module `pipecat.services.deepgram` is deprecated, use `pipecat.services.deepgram.[stt,tts]` instead.
```

**Volume:** ~10-15 unique warnings per call (some repeated per call, some only on first call).

**Root cause:** Pipecat v0.0.102 has deprecated several API surfaces. Our code uses the old APIs. Python's warnings module writes to stderr, which ECS captures into CloudWatch.

**Proposed fix:**
- Task A (suppress): Add `warnings.filterwarnings("ignore", category=DeprecationWarning, module="pipecat")` in `service_main.py` -- immediate noise reduction.
- Task B (fix): Update our code to use the new Pipecat APIs. This is the real fix but depends on API stability. Specific migrations needed:
  - `OpenAILLMContext` -> `LLMContext` + `LLMContextAggregatorPair`
  - `OpenAILLMContextFrame` -> `LLMContextFrame`
  - `pipecat.services.ai_services` -> `pipecat.services.llm_service`
  - `pipecat.services.deepgram` -> `pipecat.services.deepgram.stt` / `pipecat.services.deepgram.tts`
  - Function call handler signature -> `FunctionCallParams` single parameter
  - `vad_enabled` -> `audio_in_enabled` + `vad_analyzer`

**Recommendation:** Task A immediately, Task B as a separate feature or as part of a Pipecat version upgrade.

### 3. AWS CRT BiDi Teardown Race (InvalidStateError)

```
Exception ignored in: <class 'concurrent.futures._base.InvalidStateError'>
Traceback (most recent call last):
  File "/app/venv/lib/python3.12/site-packages/awscrt/aio/http.py", line 312, in _on_complete
    future.set_result("")
concurrent.futures._base.InvalidStateError: CANCELLED: <Future at 0x7fb7de1862d0 state=cancelled>
```

**Volume:** 2-4 lines per call teardown.

**Root cause:** Race condition in AWS CRT library during BiDi session close. Already documented in `docs/features/fix-aws-crt-bidi-teardown-race/idea.md`.

**Action:** No new work needed -- reference existing backlog item. Consider bumping priority if this confuses operators.

### 4. Daily Transport "Unable to send message before joining" Error

```
2026-02-26 23:24:00.915 | ERROR | pipecat.transports.daily.transport:send_message:1971 - Unable to send message: Unable to send messages before joining.
```

**Volume:** 1-2 per call, typically during teardown or early pipeline setup.

**Root cause:** The pipeline tries to send a message via `DailyTransport.send_message()` before the transport has fully joined the Daily room, or after it has already left. This is a timing issue in the pipeline lifecycle -- the transport's join is asynchronous, and some pipeline component is trying to send before the join completes (or after the leave).

**Proposed fix:**
- Investigate which component calls `send_message` at the wrong time. Likely candidates:
  - RTVI processor sending a config message before join completes
  - Pipeline teardown sending a goodbye/leave message after transport disconnect
- Guard the call site with a joined-state check, or defer the message until after join.
- If this is a Pipecat bug, consider filing upstream or patching locally.

## Scope Boundaries

The following are **out of scope** for this feature (already tracked elsewhere):

| Issue | Existing Backlog Item |
|-------|----------------------|
| Observer event spam (11x duplicate speaking events) | `fix-observer-event-spam` |
| AWS CRT BiDi teardown race | `fix-aws-crt-bidi-teardown-race` |
| Per-audio-frame chatty events (`audio_quality_recorded`, `silence_duration_recorded`, `metrics_observer_vad_stop`) | `fix-observer-event-spam` (related) |

## Proposed Tasks

| # | Task | Category | Effort | Impact |
|---|------|----------|--------|--------|
| 1 | Suppress pipecat DEBUG logs (`logging.getLogger("pipecat").setLevel(logging.WARNING)`) | Unstructured logs | 15 min | High -- eliminates 50-100+ lines/call |
| 2 | Suppress DeprecationWarnings from pipecat in production (`warnings.filterwarnings`) | Deprecation warnings | 15 min | Medium -- eliminates 10-15 lines/call |
| 3 | Migrate to new Pipecat APIs (LLMContext, FunctionCallParams, etc.) | Deprecation root cause | 3-4 hours | Medium -- permanent fix, removes tech debt |
| 4 | Investigate and fix Daily transport `send_message` timing | Transport error | 1-2 hours | Low-Medium -- eliminates 1-2 ERROR lines/call |

## Estimated Total Effort

Small-Medium: 1-2 hours for quick suppression (tasks 1-2), plus 4-6 hours for root cause fixes (tasks 3-4).

## Files to Investigate

- `backend/voice-agent/app/service_main.py` -- logging.basicConfig, warnings filter
- `backend/voice-agent/app/pipeline_ecs.py` -- Pipeline setup, RTVI processor, DailyTransport usage
- `backend/voice-agent/app/services/factory.py` -- Deprecated pipecat imports
- `backend/voice-agent/app/services/bedrock_llm.py` -- Deprecated pipecat import
- Pipecat source: `pipecat/transports/daily/transport.py:1971` -- send_message guard
