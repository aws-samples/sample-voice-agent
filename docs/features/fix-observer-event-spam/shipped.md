---
id: fix-observer-event-spam
name: Fix Observer Event Spam
type: bug-fix
priority: P2
effort: small
impact: medium
status: shipped
shipped: 2026-02-27
---

# Fix Observer Event Spam - Shipped

## Summary

Fixed observer event duplication that caused events like `bot_started_speaking` to fire 11 times per frame (once per processor hop). Added `_is_new_frame()` deduplication helper to all observers.

## Problem

Pipecat's observer `on_push_frame` fires once per processor hop. With ~11 processors in the pipeline, each frame triggered 11 observer calls, causing:
- `bot_started_speaking` events: 11x per actual speaking event
- `bot_stopped_speaking` events: 11x per actual stop
- `user_started_speaking` events: 11x per actual event
- Metrics and logging noise

## Solution

Added `_is_new_frame()` helper method to all 6 observers:
- `MetricsObserver`
- `ConversationObserver`
- `AudioQualityObserver`
- `TurnTrackingObserver`
- `PipelineTimingObserver`
- `InterruptionObserver`

Each observer now tracks the last seen `frame_id` and only processes events when the frame ID changes.

## Impact

| Event | Before | After |
|-------|--------|-------|
| `bot_started_speaking` | 11x per event | 1x per event |
| `bot_stopped_speaking` | 11x per event | 1x per event |
| `user_started_speaking` | 11x per event | 1x per event |

## Files Modified

- `app/observability.py` - Added `_is_new_frame()` helper to all observer classes

## Verification

- SIPp test calls show single event per speaking turn
- CloudWatch logs show 1:1 event ratio
- No duplication in conversation transcripts

## Related

- [log-noise-cleanup](./log-noise-cleanup/) - Part of comprehensive log cleanup effort
