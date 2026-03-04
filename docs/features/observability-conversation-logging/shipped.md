---
shipped: 2026-01-26
---

# Shipped: Conversation Logging

## Summary

Added conversation content logging to the voice pipeline using pipecat's non-blocking observer pattern. The ConversationObserver captures user speech, bot responses, and barge-in events for debugging and quality analysis without impacting pipeline latency.

## Key Changes

- **ConversationObserver class** in `observability.py` - Extends BaseObserver to watch frames:
  - `TranscriptionFrame` for user speech
  - `TextFrame` for bot responses (accumulated during LLM response)
  - `UserStartedSpeakingFrame` for barge-in detection during active TTS

- **Source filtering** - Only captures TextFrames from LLMService to prevent duplicate logging from TTS echo

- **Text normalization** - Joins streaming tokens with spaces and normalizes punctuation

- **Feature toggle** - `ENABLE_CONVERSATION_LOGGING` environment variable (default: false)

- **Pipeline integration** - Observer added to PipelineTask alongside MetricsObserver

## Testing

- 14 unit tests for ConversationObserver (all passing)
- 72 total tests in the suite
- 89% code coverage for observability.py
- End-to-end validated in AWS ECS deployment with real phone calls

## Log Schema

```json
{
  "event": "conversation_turn",
  "call_id": "uuid",
  "session_id": "uuid",
  "turn_number": 1,
  "speaker": "user|assistant",
  "content": "transcribed or generated text",
  "timestamp": "ISO-8601"
}
```

## CloudWatch Logs Insights Queries

```
# View conversation for a specific call
fields @timestamp, speaker, content, turn_number
| filter call_id = "your-call-id" and event = "conversation_turn"
| sort turn_number asc

# Find barge-in events
fields @timestamp, call_id, turn_number
| filter event = "barge_in"
```

## Notes

- **PII Consideration**: Feature is disabled by default. When enabled, full conversation content is logged. Consider PII implications for your use case.
- **Out of Scope**: PII redaction, audio recording, sampling rate, and opt-out mechanisms are deferred to future enhancements.
- **Security Review**: Passed with no critical/high issues. Medium findings noted for future hardening (content length limits, PII redaction).
