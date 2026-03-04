---
started: 2026-02-23
---

# Implementation Plan: Fix STT Metrics for SageMaker

## Overview

After migrating STT from cloud Deepgram WebSocket to `DeepgramSageMakerSTTService`, all STT metrics report zero/null values (`stt_final_count: 0`, `stt_confidence_avg: null`, etc.) even though transcriptions reach the LLM correctly. This is a P1 observability bug — CloudWatch dashboards and alarms for STT quality are completely blind.

**Root Cause**: Two issues in `STTQualityObserver`:

1. **Dict vs. object mismatch**: The SageMaker STT service passes `result=parsed` where `parsed` is a raw Python `dict`. The observer uses `hasattr(result, "channel")` to extract confidence, which returns `False` for dicts (dicts use key access, not attribute access). The cloud Deepgram STT passes a `LiveResultResponse` object where `hasattr` works.
2. **Missing `InterimTranscriptionFrame` handling**: The observer only listens for `TranscriptionFrame`. It never sees `InterimTranscriptionFrame` events, so `stt_interim_count` is always 0.
3. **`is_final` check fails on dicts**: `hasattr(result, "is_final")` is `False` for dicts, so `is_final` is never `True`, `_final_count` never increments, and `_record_stt_metrics()` is never called.

## Implementation Steps

### Phase 1: Fix Confidence Extraction for Dict Results (P0)

- [x] Update `STTQualityObserver._handle_transcription()` in `backend/voice-agent/app/observability.py` to handle both dict and object result formats
  - Check `isinstance(result, dict)` and use `.get()` for dict access
  - Fall back to existing `hasattr` logic for `LiveResultResponse` objects
  - Extract confidence via `result.get("channel", {}).get("alternatives", [{}])[0].get("confidence")` for dicts
  - Extract `is_final` via `result.get("is_final", False)` for dicts

### Phase 2: Add InterimTranscriptionFrame Support (P0)

- [x] Add `InterimTranscriptionFrame` import in `backend/voice-agent/app/observability.py`
  - Import from `pipecat.frames.frames`
- [x] Update `STTQualityObserver.on_push_frame()` to also handle `InterimTranscriptionFrame`
  - Route interim frames through `_handle_transcription()` with the same confidence extraction logic
  - Interim frames from SageMaker STT also carry `result=parsed` (dict) with confidence data

### Phase 3: Fix Final Count Logic (P1)

- [x] Update the final-vs-interim determination in `_handle_transcription()` to use frame type as the primary signal
  - `TranscriptionFrame` instances are always final (SageMaker only emits them when `is_final=True AND speech_final=True`)
  - `InterimTranscriptionFrame` instances are always interim
  - Remove dependency on `result.is_final` for final/interim classification — frame type is the authoritative signal
  - Keep confidence extraction from `result` for both frame types

### Phase 4: Add Word Count for Frames Without Confidence (P1)

- [x] Ensure `_record_stt_metrics()` is called even when no confidence scores are captured
  - Changed to still record `final_count`, `interim_count`, and `word_count` when confidence is unavailable
  - Pass `confidence_avg=None` and `confidence_min=None` when no scores available

### Phase 5: Update Tests (P0)

- [x] Add test cases in `backend/voice-agent/tests/test_comprehensive_observability.py` for SageMaker dict results
  - Test: dict result with confidence is extracted correctly
  - Test: dict result without confidence still counts finals and word count
  - Test: `InterimTranscriptionFrame` increments `stt_interim_count`
  - Test: mixed interim + final flow with dict results produces correct aggregated metrics
  - Test: existing `MockDeepgramResult` object tests still pass (backward compatibility)
- [x] Remove duplicate `test_no_result_attribute` test method

### Phase 6: Verification

- [x] Run existing test suite to confirm no regressions: `pytest backend/voice-agent/tests/test_comprehensive_observability.py -v` — 25/25 passed
- [x] Run full test suite: `pytest backend/voice-agent/tests/ -v` — 405/405 passed (8 pre-existing errors in unrelated e2e smoke tests)

## Technical Decisions

### 1. Frame Type as Authority for Final/Interim

Use `isinstance(frame, TranscriptionFrame)` vs `isinstance(frame, InterimTranscriptionFrame)` rather than `result.is_final`. The pipecat framework already makes this determination when emitting frames — the SageMaker STT only emits `TranscriptionFrame` when both `is_final` and `speech_final` are true (see `stt_sagemaker.py:379`). This makes the observer resilient to any STT backend.

### 2. Dual Format Support (Dict + Object)

Support both dict and object `result` formats rather than converting one to the other. This keeps the observer compatible with both cloud Deepgram (`LiveResultResponse` object) and SageMaker Deepgram (raw dict), and any future STT services.

### 3. No Changes to Pipecat Library

The fix is entirely within our observer code. We do not patch or wrap the `DeepgramSageMakerSTTService` — the dict result format is valid, our observer just needs to handle it.

## Affected Files

| File | Change |
|------|--------|
| `backend/voice-agent/app/observability.py` | Fix `STTQualityObserver` confidence extraction, add `InterimTranscriptionFrame` handling |
| `backend/voice-agent/tests/test_comprehensive_observability.py` | Add dict-result tests, interim frame tests, remove duplicate test |

## Testing Strategy

### Unit Tests

1. **Dict result confidence extraction**: Create a `TranscriptionFrame` with `result={"channel": {"alternatives": [{"confidence": 0.95}]}, "is_final": True}` and verify confidence is captured
2. **Dict result without confidence**: Verify `final_count` and `word_count` are still recorded
3. **InterimTranscriptionFrame counting**: Push interim frames and verify `interim_count` increments
4. **Mixed flow**: Push 2 interim + 1 final (all dicts) and verify aggregated metrics match expected values
5. **Backward compatibility**: Existing `MockDeepgramResult` object tests pass unchanged
6. **No result attribute**: Frames without `result` don't crash (existing test)

### Manual Verification

After deployment, make a test call and verify in CloudWatch:
- `stt_final_count > 0` in turn metrics
- `stt_confidence_avg` is populated (expected range: 0.85-0.99)
- `stt_interim_count > 0` for multi-word utterances
- `stt_word_count` matches spoken words

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| SageMaker dict format changes in pipecat upgrade | Low | Medium | Both dict and object paths tested; pipecat version pinned in requirements |
| Confidence scores absent from SageMaker responses | Low | Low | Observer already handles missing confidence gracefully; word count and final count still work |
| InterimTranscriptionFrame import breaks on older pipecat | Very Low | Low | Frame exists since pipecat 0.0.50+; we're on 0.0.102 |

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| `stt_final_count` | > 0 per turn | CloudWatch `VoiceAgent/Pipeline` namespace |
| `stt_confidence_avg` | 0.80-0.99 range | CloudWatch metric populated on test call |
| `stt_interim_count` | > 0 for multi-word turns | CloudWatch metric populated |
| `stt_word_count` | Matches spoken content | CloudWatch metric populated |
| Test pass rate | 100% | `pytest` exit code 0 |
| Existing tests | No regressions | All pre-existing tests still pass |

## Rollback Plan

1. Revert the changes to `observability.py` — metrics return to zero/null (pre-fix state)
2. No infrastructure changes, no deployment pipeline changes, no CDK changes
3. Zero risk to call quality or pipeline behavior — observers are non-blocking

## Progress Log

| Date | Update |
|------|--------|
| 2026-02-23 | Plan created from root cause analysis of STT metrics bug |
| 2026-02-23 | Implementation complete: all 6 phases done, 405/405 tests passing |
