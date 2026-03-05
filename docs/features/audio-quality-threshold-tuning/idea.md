# Audio Quality Threshold Tuning

| Field     | Value       |
|-----------|-------------|
| Type      | Bug Fix     |
| Priority  | P1          |
| Effort    | Small       |
| Impact    | Medium      |

## Problem Statement

The audio quality monitoring threshold is too sensitive for normal PSTN calls. During test call #4, the caller was speaking at normal volume with no background noise, yet the dashboard flagged 6 of 7 turns as "poor audio." The caller's mic level was -62 dB, which exceeded the poor-audio threshold of -55 dB.

From the call metrics summary:

```json
{
  "avg_rms_db": -75.0,
  "avg_peak_db": -70.4,
  "poor_audio_turns": 6,
  "turn_count": 7
}
```

The current threshold (`POOR_AUDIO_THRESHOLD_DB = -55`) was calibrated for WebRTC browser audio, not SIP/PSTN dial-in. Phone lines naturally have lower signal levels than browser microphones. This causes nearly every turn to be flagged as poor audio, making the metric useless for identifying actual audio quality problems.

## Observed Behavior

- Normal speech over PSTN dial-in registers at -62 to -75 dB RMS
- The -55 dB threshold flags this as "poor audio" on every turn
- Dashboard alarm for poor audio quality would fire on perfectly normal calls
- The `poor_audio_detected` log event fires almost continuously, adding noise

## Expected Behavior

- Normal PSTN speech should not be flagged as poor audio
- The threshold should account for the lower signal levels typical of phone lines
- Poor audio detection should only fire for genuinely degraded calls (heavy background noise, very low volume, or near-silence)

## Investigation Areas

- `app/observability.py`: `POOR_AUDIO_THRESHOLD_DB` constant and `AudioQualityObserver`
- Consider making the threshold configurable via SSM parameter
- Consider separate thresholds for WebRTC vs SIP/PSTN transport types
- Research typical RMS levels for PSTN audio to find the right baseline
