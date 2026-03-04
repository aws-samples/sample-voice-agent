---
id: log-noise-cleanup
name: Log Noise Cleanup
type: tech-debt
priority: P2
effort: medium
impact: medium
status: shipped
shipped: 2026-02-27
---

# Log Noise Cleanup - Shipped

## Summary

Eliminated four categories of log noise from the CloudWatch log stream: unstructured pipecat DEBUG logs, Python DeprecationWarnings, AWS CRT BiDi teardown race errors, and Daily transport timing errors. This builds on the foundation established by the log-analysis feature.

## What Was Delivered

### 1. Pipecat DEBUG Log Suppression

**Problem:** Pipecat's internal modules use stdlib `logging` with pipe-delimited format (~50-100 lines per call).

**Solution:** 
- Disabled pipecat DEBUG logs: `loguru.logger.disable("pipecat")`
- Set structlog to WARNING level for pipecat namespace

**Impact:** Eliminated ~50-100+ unstructured lines per call

### 2. DeprecationWarning Suppression

**Problem:** Python DeprecationWarning messages from Pipecat v0.0.102 APIs:
- `OpenAILLMContextFrame` deprecated
- Function call handler signature deprecated
- `vad_enabled` parameter deprecated
- Module path deprecations (`pipecat.services.deepgram`)

**Solution:**
- Pre-seed `pipecat.services._warned_modules` to suppress warnings at source
- Added `warnings.filterwarnings("ignore", category=DeprecationWarning, module="pipecat")`

**Impact:** Eliminated ~10-15 warning lines per call

**Note:** Root cause fix (migrating to new Pipecat APIs) deferred to future Pipecat version upgrade.

### 3. AWS CRT BiDi Teardown Race Fix

**Problem:** `InvalidStateError` tracebacks during BiDi session close (2-4 lines per call).

**Solution:** 
- Reordered `_disconnect()` in TTS service: close BiDi session before cancelling tasks
- Added 2-second grace period for response task shutdown
- Downgraded `ModelStreamError` during teardown from ERROR to DEBUG
- Created STT wrapper subclass with same graceful teardown pattern

**Impact:** Zero `InvalidStateError` tracebacks, zero `AWS_ERROR_UNKNOWN` errors

**Files Modified:**
- `app/services/deepgram_sagemaker_tts.py`
- `app/services/deepgram_sagemaker_stt.py` (new wrapper)
- `app/services/factory.py` (use wrapper)

### 4. Daily Transport Timing (Addressed via Related Fixes)

**Problem:** "Unable to send message before joining" errors during teardown.

**Status:** This was a symptom of the BiDi teardown race. After fixing the race condition and ensuring proper cleanup order, these errors no longer appear in logs.

## Files Modified

| File | Changes |
|------|---------|
| `app/service_main.py` | Pipecat log suppression, warnings filter |
| `app/pipeline_ecs.py` | Pre-seed `_warned_modules` for deprecation suppression |
| `app/services/deepgram_sagemaker_tts.py` | Graceful teardown, error level adjustments |
| `app/services/deepgram_sagemaker_stt.py` | New wrapper with graceful teardown |
| `app/services/factory.py` | Use STT wrapper subclass |

## Verification

- **SIPp Test Calls:** 30-second calls complete with clean log streams
- **Log Stream Analysis:** Only structured JSON events, no pipe-delimited pipecat logs
- **Error Count:** Zero `InvalidStateError`, zero `AWS_ERROR_UNKNOWN`
- **Deprecation Warnings:** Zero warnings in production logs

## Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Unstructured logs** | 50-100+ lines/call | 0 lines | Complete elimination |
| **Deprecation warnings** | 10-15 lines/call | 0 lines | Complete elimination |
| **Error tracebacks** | 2-4 lines/call | 0 lines | Complete elimination |
| **Log queryability** | Mixed formats | Pure JSON | CloudWatch Insights works cleanly |

## Related Features

- [log-analysis](./log-analysis/) - Foundation structured logging work
- [fix-observer-event-spam](./fix-observer-event-spam/) - Observer deduplication
- [fix-aws-crt-bidi-teardown-race](./fix-aws-crt-bidi-teardown-race/) - BiDi teardown fix (part of this cleanup)

## Notes

- All fixes are at the source except for deprecation warnings (suppressed, not fixed)
- No functional changes to application behavior
- Tests: 454 passing (including 11 new BiDi teardown tests)
