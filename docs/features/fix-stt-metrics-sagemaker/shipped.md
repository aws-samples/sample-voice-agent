---
id: fix-stt-metrics-sagemaker
name: Fix STT Metrics for SageMaker
type: Bug Fix
priority: P1
effort: Small
impact: Medium
created: 2026-02-23
shipped: 2026-02-23
---

# Fix STT Metrics for SageMaker - Shipped

## Summary

Fixed the `STTQualityObserver` to correctly capture STT metrics from the `DeepgramSageMakerSTTService`. After the SageMaker STT migration, all STT metrics (`stt_final_count`, `stt_confidence_avg`, `stt_interim_count`, `stt_word_count`) were reporting zero/null because the observer was incompatible with the SageMaker STT's dict-based result format.

## Root Cause

Three issues in `STTQualityObserver`:

1. **Dict vs. object mismatch**: SageMaker STT passes `result` as a raw Python `dict`, but the observer used `hasattr(result, "channel")` which returns `False` for dicts. Confidence was never extracted.
2. **Missing `InterimTranscriptionFrame` handling**: The observer only listened for `TranscriptionFrame`, so `stt_interim_count` was always 0.
3. **`is_final` check failed on dicts**: `hasattr(result, "is_final")` returns `False` for dicts, so `_final_count` never incremented and `_record_stt_metrics()` was never called.

## What Was Fixed

- **Dual format confidence extraction**: New `_extract_confidence()` method handles both dict results (SageMaker: `result.get("channel", {}).get("alternatives", [])`) and object results (cloud Deepgram: `result.channel.alternatives[0].confidence`)
- **InterimTranscriptionFrame support**: Observer now listens for both `TranscriptionFrame` (final) and `InterimTranscriptionFrame` (interim), checking the subclass first due to inheritance
- **Frame-type-based classification**: Final/interim determination uses `isinstance` on frame type rather than `result.is_final`, making it resilient to any STT backend
- **Metrics without confidence**: `_record_stt_metrics()` now records `final_count`, `interim_count`, and `word_count` even when confidence scores are unavailable

## Files Modified

| File | Change |
|------|--------|
| `backend/voice-agent/app/observability.py` | Added `InterimTranscriptionFrame` import; rewrote `STTQualityObserver` with `_extract_confidence()`, dual-format support, and frame-type classification |
| `backend/voice-agent/tests/test_comprehensive_observability.py` | Added 4 new tests (dict confidence, dict without confidence, mixed interim+final flow, interim counting); fixed existing test to use `InterimTranscriptionFrame`; removed duplicate test method |

## Test Results

- **25/25** observability tests passing
- **405/405** full test suite passing
- No regressions

## Production Verification

Deployed to ECS (task definition v15) and verified on live call `68d38c55`:

```
stt_quality_recorded:
  confidence_avg: 0.939
  confidence_min: 0.696
  interim_count: 4
  final_count: 1
  word_count: 14
```

CloudWatch EMF confirmed emitting `STTConfidenceAvg`, `STTConfidenceMin`, `STTWordCount` to the `VoiceAgent/Pipeline` namespace.

## Quality Gates

| Gate | Result | Notes |
|------|--------|-------|
| Security Review | APPROVED | All 5 categories passed: input validation, injection risks, data exposure, DoS, type safety |
| QA Validation | APPROVED | All code paths tested, full suite green, production metrics verified as reasonable |

## Success Criteria

- [x] `stt_final_count > 0` per turn
- [x] `stt_confidence_avg` in 0.80-0.99 range (actual: 0.939)
- [x] `stt_interim_count > 0` for multi-word turns (actual: 4)
- [x] `stt_word_count` matches spoken content (actual: 14)
- [x] All existing tests pass without regression
- [x] CloudWatch dashboard metrics populated
