---
name: Fix Observer Event Spam
type: bug
priority: P2
effort: small
impact: medium
status: completed
created: 2026-02-23
shipped: 2026-02-27
related-to: observability-quality-monitoring, observability-conversation-logging
depends-on: []
---

# Fix Observer Event Spam

## Problem Statement

The `ConversationObserver` emits duplicate `conversation_observer_bot_started_speaking`, `conversation_observer_bot_stopped_speaking`, and `conversation_observer_user_started_speaking` log events -- **11 copies per state change** instead of 1.

Observed during a live call on 2026-02-23:
- Bot greeting: 11x `bot_started_speaking` at `23:18:25.038` (within 3ms)
- Bot greeting end: 11x `bot_stopped_speaking` at `23:18:29.034`
- User started speaking: 11x `user_started_speaking` at `23:18:30.082`
- Bot second utterance: 11x `bot_started_speaking` at `23:18:37.025`
- Bot second utterance end: 11x `bot_stopped_speaking` at `23:18:59.385`

**Total: 55 spam log lines for 5 actual state transitions** (should be 5 lines).

## Root Cause

The pipeline has 11 observers registered (metrics, audio_quality, stt_quality, llm_quality, conversation_flow, conversation, plus linked pipeline processors). When pipecat dispatches a `BotStartedSpeakingFrame` or `BotStoppedSpeakingFrame`, it fans out to every observer. Each observer's handler independently logs the event, producing N duplicates where N is the number of registered observers.

The `ConversationObserver` is receiving the speaking state frame once per downstream processor in the pipeline, not once per actual state transition.

## Impact

- **CloudWatch log noise**: 11x more log events than necessary for speaking state changes
- **CloudWatch costs**: Each duplicate is a separate log event billed by CloudWatch
- **Log analysis difficulty**: Grep/filter for speaking events returns 11x results, making it harder to track actual conversation flow

No functional impact -- the bot behaves correctly. This is purely a logging/observability issue.

## Proposed Solution

Deduplicate in the observer by tracking the last-emitted speaking state and only logging on actual transitions:

```python
class ConversationObserver:
    def __init__(self):
        self._bot_speaking = False
        self._user_speaking = False

    async def on_bot_started_speaking(self, ...):
        if self._bot_speaking:
            return  # Already in speaking state, skip duplicate
        self._bot_speaking = True
        # ... emit log event

    async def on_bot_stopped_speaking(self, ...):
        if not self._bot_speaking:
            return  # Already in stopped state, skip duplicate
        self._bot_speaking = False
        # ... emit log event
```

Alternatively, investigate why pipecat is delivering speaking frames to each observer -- the issue may be in how observers are registered with the pipeline task.

## Files to Investigate

- `backend/voice-agent/app/observers/conversation_observer.py` -- Add state dedup logic
- `backend/voice-agent/app/pipeline_ecs.py` -- Check how observers are added to the pipeline task (lines ~370-420)
- Pipecat source: `pipecat/pipeline/task.py` -- Understand observer dispatch model

## Estimated Effort

Small -- ~1-2 hours. Simple state-tracking dedup in the observer.
