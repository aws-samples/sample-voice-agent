---
id: transition-tts-conversation-logging
name: Transition TTS Conversation Logging
type: bug-fix
priority: P2
effort: Small
impact: Low
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Transition TTS Conversation Logging

## Summary

Fixed a gap in conversation logging where transition TTS phrases ("One moment please."), filler phrases, and deterministic tool-spoken responses were spoken to the caller but invisible in logs and the dashboard transcript. These non-LLM TTS events now appear in conversation logs with `speaker: "system"` to distinguish them from LLM-generated assistant speech.

## What Was Built

### TTSSpeakFrame Observation
- Added `TTSSpeakFrame` handling to `ConversationObserver.on_push_frame()`
- Source filtering: skips LLM-origin frames (already logged as `speaker: "assistant"`)
- Deduplication via `_is_new_frame()` to prevent double-logging

### Captured TTS Sources
- **Transition phrases**: pipecat-flows `pre_actions` TTS (e.g., "One moment please.")
- **Filler phrases**: `FunctionCallFillerProcessor` TTS during tool execution delays
- **Spoken responses**: deterministic `spoken_response` TTS from tool results

### Design Decisions
- Observer pattern (not FrameProcessor) -- consistent with existing conversation logging
- `speaker: "system"` distinguishes non-LLM TTS from LLM-generated responses
- No turn number increment for system TTS -- turn tracking remains conversation-scoped

## Files Changed

### Modified Files
- `app/observability.py` -- TTSSpeakFrame handling in ConversationObserver
- `tests/test_observability_metrics.py` -- 5 new unit tests
- `AGENTS.md` -- documentation for `speaker: "system"` log entries

## Quality Gates

### QA Validation: PASS
- 5 new unit tests -- all passing
- Transition TTS, filler phrases, and spoken responses all appear in logs
- LLM-origin TTS correctly filtered (no double-logging)
- Dashboard transcript shows complete conversation including system TTS

### Security Review: PASS
- Read-only observation of existing TTS frames -- no new data flows
- System TTS content is deterministic (not user-provided) -- no injection risk
- No PII in transition or filler phrases
