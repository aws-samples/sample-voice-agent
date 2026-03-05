---
id: audio-quality-threshold-tuning
name: Audio Quality Threshold Tuning
type: bug-fix
priority: P1
effort: Small
impact: Medium
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Audio Quality Threshold Tuning

## Summary

Fixed false-positive poor audio detection for PSTN/SIP dial-in calls. The previous threshold of -55 dBFS was calibrated for WebRTC browser audio, but normal PSTN speech registers at -62 to -75 dB RMS, causing nearly every turn (6 of 7 in test calls) to be flagged as "poor audio." Lowered the default threshold to -70 dBFS and introduced dual-signal detection requiring both low RMS *and* low STT confidence before flagging a turn.

## What Was Built

### Threshold Adjustment
- Default `POOR_AUDIO_THRESHOLD_DB` lowered from -55 dB to -70 dB
- Made configurable via SSM parameter `/voice-agent/config/poor-audio-threshold-db` with env var fallback
- Single threshold approach (not transport-dependent) since the project only uses PSTN dial-in

### Dual-Signal Poor Audio Detection
- Changed from single-signal (RMS only) to dual-signal detection
- A turn is flagged as poor ONLY when BOTH conditions are met:
  1. RMS is below the threshold (-70 dBFS default)
  2. STT confidence is absent or below 0.9
- Eliminates false positives on quiet but clear PSTN audio (STT confidence 0.997-0.999 even at -88 dBFS)
- Detection moved from `AudioQualityObserver` to `MetricsCollector.end_turn()` because `UserStoppedSpeakingFrame` fires before `TranscriptionFrame`

### RMS Distribution Metrics
- Added per-turn `audio_rms_min_db`, `audio_rms_max_db`, `audio_rms_stddev_db` metrics
- Dashboard widget shows RMS Min/Max alongside Avg RMS for data-driven threshold tuning

## Files Changed

### Modified Files
- `app/observability.py` -- dual-signal detection, RMS distribution metrics, configurable threshold
- `app/services/config_service.py` -- SSM parameter for threshold
- `app/pipeline_ecs.py` -- wire configurable threshold through pipeline
- `app/service_main.py` -- config plumbing
- `infrastructure/src/constructs/voice-agent-monitoring-construct.ts` -- dashboard annotation updated from -55 to -70
- `tests/test_observability_metrics.py` -- updated tests for dual-signal detection
- `AGENTS.md` -- documentation updates

## Quality Gates

### QA Validation: PASS
- All existing observability tests updated and passing
- Dual-signal detection verified: quiet-but-clear audio no longer flagged
- RMS distribution metrics emitting correctly
- SSM parameter override verified

### Security Review: PASS
- No new attack surface -- threshold is a numeric SSM parameter
- No PII implications
- Metrics are aggregated, not per-user
