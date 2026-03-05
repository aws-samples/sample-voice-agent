# Transition TTS Not Captured in Conversation Logs

| Field     | Value       |
|-----------|-------------|
| Type      | Bug Fix     |
| Priority  | P2          |
| Effort    | Small       |
| Impact    | Low         |

## Problem Statement

When the flow system plays transition TTS phrases (e.g., "One moment please.") via the `pre_actions` mechanism in Pipecat Flows, the spoken text does not appear in the conversation logs or dashboard transcript. This creates a gap in the conversation record -- the caller hears the phrase, but it is invisible in the logs.

The `ConversationObserver` captures LLM-generated speech via `on_first_tts_chunk` and `on_bot_stopped_speaking`, but `pre_actions` TTS is injected directly by the FlowManager as a `TTSSpeakFrame` before the node transition, bypassing the LLM pipeline path that the observer monitors.

## Observed Behavior

- Transition TTS like "One moment please." is spoken to the caller
- The phrase does not appear in `conversation_turn` log events
- The dashboard transcript shows a gap between the last agent utterance and the first utterance in the new node
- No `speaker: "system"` or equivalent entry exists for flow-injected TTS

## Expected Behavior

- All TTS spoken to the caller should appear in the conversation log
- Transition TTS could be logged as `speaker: "system"` to distinguish from LLM-generated speech
- The dashboard transcript should show the complete caller experience with no gaps

## Investigation Areas

- `app/observability.py`: `ConversationObserver` -- how it captures bot speech
- Pipecat Flows `pre_actions` mechanism -- where `TTSSpeakFrame` is queued
- Consider hooking into the `TTSSpeakFrame` processing in the pipeline to capture all TTS output
- Alternative: emit a synthetic `conversation_turn` event from the transition handler in `transitions.py`
