---
started: 2026-01-26
---

# Implementation Plan: Conversation Logging

## Overview

Add conversation content logging to the voice pipeline using pipecat's observer pattern. This enables debugging "wrong response" issues and analyzing conversation quality without impacting pipeline latency.

**Key Approach**: ConversationObserver class extending BaseObserver (same pattern as MetricsObserver) to watch TranscriptionFrame, TextFrame, and barge-in events non-blockingly.

## Implementation Steps

- [x] Step 1: Create ConversationObserver class in observability.py
  - Extend BaseObserver
  - Watch TranscriptionFrame for user speech (final transcripts only)
  - Watch TextFrame for bot responses (accumulate streaming chunks)
  - Detect barge-in when UserStartedSpeakingFrame during active TTS
  - Accept MetricsCollector for turn correlation

- [x] Step 2: Add conversation logging methods
  - `_log_conversation_turn()` - logs user/assistant speech with call_id, session_id, turn_number, speaker, content
  - `_log_barge_in()` - logs interruption events
  - Use structlog JSON format consistent with existing patterns

- [x] Step 3: Integrate ConversationObserver into pipeline
  - Add ENABLE_CONVERSATION_LOGGING environment variable (default: False)
  - Instantiate ConversationObserver in pipeline_ecs.py alongside MetricsObserver
  - Add to observers list in PipelineTask

- [x] Step 4: Write unit tests
  - Test TranscriptionFrame capture
  - Test TextFrame accumulation and logging at TTS boundary
  - Test barge-in detection (UserStartedSpeakingFrame during TTS)
  - Test logging disabled when ENABLE_CONVERSATION_LOGGING=False
  - 11 tests added, all passing

- [ ] Step 5: Update documentation
  - Add CloudWatch Logs Insights query examples to operational docs
  - Document PII considerations and feature toggle

## Technical Decisions

### Observer Pattern (Not FrameProcessor)
- Observers run in separate async tasks - cannot block the pipeline
- MetricsObserver already proves this pattern works
- No risk of audio delays from logging operations

### Frame Types to Capture
| Frame | What We Log | Why |
|-------|-------------|-----|
| TranscriptionFrame | User's transcribed speech | Final STT output (not interim) |
| TextFrame | Bot's generated response | Accumulate chunks until TTS boundary |
| UserStartedSpeakingFrame | Barge-in detection | When received during active TTS |
| TTSStartedFrame / TTSStoppedFrame | TTS state tracking | Know when bot is "speaking" |

### Log Schema
```json
{
  "event": "conversation_turn",
  "call_id": "uuid",
  "session_id": "uuid",
  "turn_number": 1,
  "speaker": "user|assistant|system",
  "content": "transcribed or generated text",
  "timestamp": "ISO-8601"
}
```

Speaker values:
- `"user"` -- caller's transcribed speech (from STT)
- `"assistant"` -- LLM-generated bot response
- `"system"` -- non-LLM TTS: transition phrases, filler phrases, tool spoken responses

## Testing Strategy

- **Unit tests**: Mock frame events, verify log output format and content
- **Integration tests**: End-to-end with test audio, verify logs appear in structured format
- **Performance validation**: Confirm <1ms logging overhead via E2E latency metrics

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| TextFrame streaming produces fragmented logs | Accumulate text until TTS boundary before logging |
| PII logged without redaction | Feature toggle default OFF; document in runbook |
| Log volume increases CloudWatch costs | Monitor costs; sample rate config is future enhancement |

## Acceptance Criteria

- [x] User speech logged from TranscriptionFrame with call_id, turn_number, timestamp
- [x] Bot responses logged from TextFrame (accumulated) with same fields
- [x] Barge-in events logged when user interrupts active TTS
- [x] JSON log format consistent with existing structlog patterns
- [x] Non-blocking implementation using observer pattern (<1ms overhead)
- [x] Feature toggle via ENABLE_CONVERSATION_LOGGING environment variable

## Out of Scope

- PII redaction (future enhancement)
- Caller opt-out mechanism
- Full transcript assembly
- Sampled verbose logging (10% mode)
- Audio recording
