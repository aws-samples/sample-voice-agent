---
started: 2026-01-26
---

# Implementation Plan: Conversation Turn Tracking

## Overview

This feature adds interruption count tracking to the observability module. Turn counting already exists via `MetricsObserver.start_turn()`, but interruption (barge-in) events are logged individually without being aggregated into a count that appears in the call summary.

**Current State:**
- Turn counting works: `MetricsObserver` calls `collector.start_turn()` on `UserStartedSpeakingFrame`
- Barge-in events are logged: `ConversationObserver._log_barge_in()` emits `barge_in` log events
- Missing: Interruption count aggregation and CloudWatch metric

**Goal:** Add `interruption_count` to `CallMetrics` and emit it in the call summary EMF log.

## Implementation Steps

- [x] Step 1: Add `interruption_count` field to `CallMetrics` dataclass in `observability.py`
- [x] Step 2: Add `record_interruption()` method to `MetricsCollector` to increment the counter
- [x] Step 3: Update `ConversationObserver._log_barge_in()` to call `collector.record_interruption()`
- [x] Step 4: Add `InterruptionCount` metric to `EMFLogger.emit_call_summary()`
- [x] Step 5: Add unit tests for interruption tracking
- [x] Step 6: Update `CallMetrics.to_dict()` to include `interruption_count`

## Technical Decisions

1. **Interruption tracking in ConversationObserver** - The observer already detects barge-ins, so we just need to add a counter call
2. **No separate InterruptionObserver** - Keep the logic in ConversationObserver since barge-in detection requires TTS state tracking
3. **Metric as Count type** - InterruptionCount is a simple counter, not a timing metric

## File Changes

| File | Change |
|------|--------|
| `backend/voice-agent/app/observability.py` | Add interruption_count field and tracking |
| `backend/voice-agent/tests/test_observability_metrics.py` | Add tests for interruption tracking |

## Testing Strategy

1. Unit tests for `MetricsCollector.record_interruption()` method
2. Unit tests verifying `ConversationObserver` increments counter on barge-in
3. Verify `call_summary` EMF includes `InterruptionCount`

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| ConversationObserver may be disabled | Only track interruptions when observer is enabled (matches current behavior) |
| Double counting if multiple observers | Only ConversationObserver tracks barge-ins, MetricsObserver doesn't |
