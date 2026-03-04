---
name: Conversational Delay Handling
type: feature
priority: P1
effort: small
impact: medium
status: idea
created: 2026-01-27
blocked-by: tool-calling-framework
---

# Conversational Delay Handling

## Problem Statement

When tools take 3-5+ seconds to execute (database queries, API calls), silence creates an awkward caller experience. The agent should use natural filler phrases ("Let me look that up for you...", "One moment while I check your account...") to maintain conversational flow and reassure the caller that processing is happening.

## Proposed Solution

Implement a filler phrase system that:
1. Detects when a tool execution or LLM response will exceed a threshold (e.g., 1.5 seconds)
2. Immediately speaks a contextually appropriate filler phrase
3. Continues with the actual response once processing completes
4. Avoids interrupting the filler if the response arrives quickly

## Technical Approach

### Filler Phrase Categories

**Tool-Specific Fillers**:
- Account lookup: "Let me pull up your account information..."
- Order status: "I'm checking on that order for you now..."
- Database query: "One moment while I look that up..."
- Ticket creation: "I'm creating a support ticket for you..."

**Generic Fillers**:
- "Just a moment..."
- "Let me check on that..."
- "One second while I look into this..."
- "Bear with me for just a moment..."

### Implementation

1. **Delay Detection**:
   - Start a timer when tool execution begins
   - If no response within threshold, trigger filler

2. **Filler Selection**:
   - Match filler to tool type when known
   - Use generic filler for unknown delays
   - Avoid repeating the same filler consecutively

3. **Audio Coordination**:
   - Pre-synthesize common fillers for instant playback
   - Queue actual response to play after filler completes
   - Handle case where response arrives during filler (wait for natural pause)

### Pipeline Integration

```python
async def execute_tool_with_filler(tool_call, pipeline):
    filler_task = asyncio.create_task(
        schedule_filler(tool_call.name, delay=1.5)
    )
    result = await execute_tool(tool_call)
    filler_task.cancel()  # Cancel if not yet triggered
    return result
```

## Affected Areas

- `backend/voice-agent/app/pipeline_ecs.py` - Inject filler during tool execution
- `backend/voice-agent/app/services/bedrock_llm.py` - Coordinate with tool execution timing
- New: `backend/voice-agent/app/filler_phrases.py` - Filler phrase selection logic
- Potentially: Pre-synthesized audio cache for common fillers

## Filler Phrase Guidelines

1. **Natural**: Sound like a human assistant, not robotic
2. **Reassuring**: Confirm action is being taken
3. **Brief**: 2-4 seconds maximum
4. **Varied**: Don't repeat the same phrase multiple times
5. **Contextual**: Match the filler to the operation when possible

## Success Criteria

- [ ] Filler plays within 1.5s of tool execution start
- [ ] Filler is contextually appropriate to the operation
- [ ] No awkward overlaps between filler and actual response
- [ ] User feedback indicates improved experience during waits
- [ ] Fillers don't repeat consecutively in same conversation

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FILLER_DELAY_THRESHOLD_MS` | `1500` | Delay before triggering filler |
| `ENABLE_FILLER_PHRASES` | `true` | Enable/disable filler system |
| `FILLER_VOICE_PRESET` | `same` | Use same voice as agent or different |

## Dependencies

- `tool-calling-framework` - Primary use case is during tool execution
- TTS service for synthesizing fillers (or pre-cached audio)

## Related Features

- `tool-calling-framework` - Triggers most delay scenarios
- `knowledge-base-rag` - RAG retrieval could also trigger delays
