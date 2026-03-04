---
started: 2026-01-27
---

# Implementation Plan: Conversational Delay Handling

## Overview

Implement filler phrases that play during tool execution delays to maintain natural conversation flow. When a tool is called, the system speaks a contextually appropriate phrase like "Let me look that up for you..." to reassure the caller that processing is happening.

## Architecture (Final Implementation)

The solution uses a `FunctionCallFillerProcessor` that intercepts `FunctionCallsStartedFrame` (emitted when the LLM decides to call a tool) and pushes a TTSSpeakFrame with a filler phrase before the tool executes.

```
LLM decides to call tool
        │
        ▼
┌──────────────────────────────────┐
│ FunctionCallsStartedFrame emitted │
└──────────────────────────────────┘
        │
        ▼
┌──────────────────────────────────┐
│ FunctionCallFillerProcessor      │
│ intercepts and pushes filler     │
│ TTSSpeakFrame                    │
└──────────────────────────────────┘
        │
        ├──▶ Filler phrase → TTS → plays immediately
        │
        ▼
┌──────────────────────────────────┐
│ Tool execution happens           │
│ (filler plays during this)       │
└──────────────────────────────────┘
        │
        ▼
    Tool result → LLM → Response
```

**Key Insight**: The filler is spoken BEFORE the tool executes (not after a delay threshold), so it's part of the natural conversation flow. The filler becomes part of the conversation context, which is appropriate since the assistant is saying "let me look that up."

## Implementation Steps

- [x] Step 1: Create filler phrases module
  - Create `backend/voice-agent/app/filler_phrases.py`
  - Define FillerPhraseManager class with phrase selection logic
  - Implement tool-specific and generic phrase categories
  - Add consecutive phrase deduplication

- [x] Step 2: Create FunctionCallFillerProcessor
  - Create `backend/voice-agent/app/function_call_filler_processor.py`
  - Intercept `FunctionCallsStartedFrame` in pipeline
  - Push `TTSSpeakFrame` with contextual filler phrase
  - Support function-specific phrases (e.g., "get_customer_info" → "Let me pull up your account...")

- [x] Step 3: Integrate with pipeline
  - Add `FunctionCallFillerProcessor` after LLM, before TTS
  - Configure via `ENABLE_FILLER_PHRASES` environment variable
  - Pipeline: `LLM → FunctionCallFillerProcessor → TTS → Output`

- [x] Step 4: Add tests
  - Test processor initialization and configuration
  - Test phrase selection (function-specific and generic)
  - Test phrase deduplication
  - Test disabled configuration

## Technical Decisions

### 1. FunctionCallFillerProcessor Approach (Final Solution)

Instead of injecting audio after a delay threshold, intercept `FunctionCallsStartedFrame` and speak immediately:

**Advantages:**
- The filler is part of the normal pipeline flow
- No timing/race conditions with tool responses
- The filler appropriately becomes part of conversation context
- Works with Cartesia's word timestamp mechanism (no context pollution issue)

**How it works:**
1. LLM decides to call a tool → `FunctionCallsStartedFrame` emitted
2. `FunctionCallFillerProcessor` intercepts and pushes `TTSSpeakFrame`
3. TTS speaks the filler while tool executes
4. Tool result arrives, LLM continues response

### 2. Function-Specific Phrases

Map known function names to specific phrases:
```python
FUNCTION_PHRASES = {
    "get_customer_info": ["Let me pull up your account..."],
    "check_order_status": ["Let me check on that order..."],
    "get_current_time": ["Let me check the time..."],
}
```
Fall back to generic phrases for unknown functions.

## File Structure

```
backend/voice-agent/app/
├── filler_phrases.py               # Phrase manager (legacy, still used for unit tests)
├── function_call_filler_processor.py  # NEW: Pipeline processor
├── pipeline_ecs.py                 # Modified: Adds processor to pipeline
└── tools/
    └── builtin/
        └── slow_echo_tool.py       # Testing tool with 2s delay

backend/voice-agent/tests/
├── test_filler_phrases.py          # Unit tests for phrase manager
└── test_filler_integration.py      # Integration tests for processor
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_FILLER_PHRASES` | `true` | Enable/disable filler processor |

## Testing Strategy

### Unit Tests
- `test_filler_phrases.py`: Phrase selection, deduplication, tool mapping
- `test_filler_integration.py`: Processor initialization, phrase selection, configuration

### Manual Testing
- Deploy with `ENABLE_TOOL_CALLING=true` and `ENABLE_FILLER_PHRASES=true`
- Call slow_echo tool: "slowly echo hello" → should hear filler phrase, then result
- Call time tool (fast): should hear filler phrase, then time

## Success Criteria

- [x] Filler plays when tool call starts
- [x] Filler is contextually appropriate to the function name
- [x] Fillers don't repeat consecutively in same conversation
- [x] Feature can be disabled via environment variable
- [ ] Manual testing confirms filler plays during slow tool execution

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| TTS latency delays filler | Acceptable (~100-200ms), not noticeable |
| User confused by filler | Phrases are natural, reassuring |
| Too many fillers in long conversations | Deduplicate consecutive phrases |
| Filler for fast tools | Acceptable - user hears "Let me check" then immediately gets result |

## Dependencies

- **tool-calling-framework** (shipped ✓) - Provides `FunctionCallsStartedFrame`
- **CartesiaTTSService** - Synthesizes filler phrases
- **Pipecat FrameProcessor** - Base class for custom processors

## Previous Approach (Deprecated)

The original approach used delayed injection via `task.queue_frame()`:
- Start filler task with 1.5s delay when tool handler called
- Cancel if tool returns quickly
- **Problem**: Caused context pollution (filler text interleaved with LLM response)

This was abandoned in favor of the `FunctionCallFillerProcessor` approach.

## Progress Log

| Date | Update |
|------|--------|
| 2026-01-27 | Plan created |
| 2026-01-27 | Initial implementation: filler_phrases.py, pipeline integration |
| 2026-01-27 | Discovered context pollution issue with TTSSpeakFrame injection |
| 2026-01-27 | Researched LLMPreSpeakProcessor pattern from AWS blog and Pipecat issues |
| 2026-01-27 | Implemented FunctionCallFillerProcessor approach - intercepts FunctionCallsStartedFrame |
| 2026-01-27 | All 243 tests passing, feature enabled by default |
