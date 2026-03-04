---
shipped: 2026-01-27
---

# Shipped: Conversation Turn Tracking

## Summary

Added interruption count (barge-in) tracking to the observability module. The `InterruptionCount` metric is now emitted in the call summary EMF log and available as a CloudWatch metric.

## Key Changes

- Added `interruption_count` field to `CallMetrics` dataclass
- Added `record_interruption()` method to `MetricsCollector`
- Updated `ConversationObserver` to detect barge-ins using `BotStartedSpeakingFrame`/`BotStoppedSpeakingFrame` (tracks actual audio playback, not TTS generation)
- Added deduplication logic to count only one interruption per bot speaking session
- Added `InterruptionCount` metric to EMF call summary
- Added comprehensive unit tests for interruption tracking

## Testing

- 55 unit tests passing including new interruption-specific tests
- Live testing with phone calls verified:
  - Barge-ins are correctly detected when user speaks while bot audio is playing
  - InterruptionCount accurately reflects number of interruptions per call
  - No duplicate counting due to multiple observers

## Technical Notes

- Initially used `TTSStartedFrame`/`TTSStoppedFrame` for barge-in detection, but these track TTS *generation* not playback
- Switched to `BotStartedSpeakingFrame`/`BotStoppedSpeakingFrame` which track actual audio output
- Added `_barge_in_detected` flag to prevent duplicate counts when frames are delivered to multiple observers

## CloudWatch Metrics

The `call_summary` EMF log now includes:
```json
{
  "TurnCount": 2,
  "InterruptionCount": 2,
  ...
}
```

Both metrics are published to the `VoiceAgent/Pipeline` namespace.
