---
id: observability-turn-tracking
name: Conversation Turn Tracking
type: Enhancement
priority: P2
effort: Small
impact: Medium
created: 2026-01-26
---

# Conversation Turn Tracking

## Problem Statement

The `call_summary` log currently shows `turn_count: 0` for all calls because we haven't wired up turn tracking to pipeline events. This means:

1. **No conversation depth visibility** - We can't tell if a call had 2 exchanges or 20. Longer conversations may indicate engaged users or stuck conversations.

2. **No interruption tracking** - We don't know how often users barge-in (interrupt the bot). High interruption rates may indicate latency issues or bot responses that are too long.

3. **Missing call quality signal** - Turn count combined with duration gives "turns per minute" - a key indicator of conversation flow and naturalness.

## Why This Matters

- **Call Quality**: A 60-second call with 2 turns vs 10 turns tells very different stories
- **Bot Tuning**: High interruption counts may signal bot responses need to be shorter
- **User Engagement**: Turn count patterns help identify successful vs abandoned calls

## Proposed Solution

1. Hook into pipecat's frame events (or context aggregator) to detect user/assistant turns
2. Increment `turn_count` in `_run_pipeline()` when user completes a turn
3. Optionally track `interruption_count` separately (barge-ins)
4. Include both in the `call_summary` log

## Affected Areas

- backend/voice-agent/app/service_main.py (turn counter in _run_pipeline)
- backend/voice-agent/app/pipeline_ecs.py (event handler for turns)
