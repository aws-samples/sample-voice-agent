---
id: observability-conversation-logging
name: Conversation Logging
type: Enhancement
priority: P2
effort: Medium
impact: Medium
created: 2026-01-26
---

# Conversation Logging

## Problem Statement

The voice agent doesn't log conversation content:

1. **No transcription logging** - User speech (from Deepgram STT) isn't captured. When debugging call issues, we can't see what the user actually said.

2. **No LLM response logging** - Bot responses aren't logged. We can't review what the agent said or analyze response quality.

3. **No interruption tracking** - When users barge-in (interrupt the bot), we don't capture when this happens or how often.

## Why This Matters

- **Debugging**: "The bot said something weird" reports are impossible to investigate without conversation logs
- **Quality Analysis**: Can't analyze conversation patterns, identify common questions, or improve prompts
- **Compliance**: Some use cases may require conversation records

## Proposed Solution

1. **ConversationLogger FrameProcessor**: Create a pipeline processor that logs:
   - User speech (from TranscriptionFrame)
   - Bot responses (from TextFrame)
   - Interruptions (from UserStartedSpeakingFrame)

2. **Sampled Full Logging**: Enable detailed frame-level logging for 10% of calls to aid debugging without overwhelming storage

## Privacy Considerations

- Consider PII implications of logging conversation content
- May need configurable redaction or opt-out
- Storage retention policies

## Affected Areas

- backend/voice-agent/app/pipeline_ecs.py
- backend/voice-agent/app/conversation_logger.py (new file)
