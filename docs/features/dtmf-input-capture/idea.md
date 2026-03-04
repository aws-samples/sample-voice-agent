---
name: DTMF Input Capture
type: feature
priority: P1
effort: medium
impact: high
status: idea
created: 2026-02-23
related-to: authentication-tool, payment-processing-tool
depends-on: []
---

# DTMF Input Capture

## Problem Statement

Callers on PSTN lines frequently need to enter structured data via their phone keypad -- account numbers, menu selections, PIN codes, or confirmation digits. Today the voice agent can only accept spoken input through the STT pipeline, which is unreliable for numeric sequences (e.g., "one five oh three" vs "1503") and inappropriate for sensitive data that should not be transcribed.

Without DTMF (Dual-Tone Multi-Frequency) capture, the agent cannot support standard IVR-style interactions that callers expect from any phone-based system. This blocks downstream features like authentication (PIN entry), payment processing (card numbers), and menu-driven routing.

## Vision

Enable the voice agent to receive and process DTMF keypad input from callers during a live call. DTMF digits are captured as discrete events, accumulated into complete input sequences (terminated by `#` or a timeout), and surfaced to the LLM as structured tool results or injected into the conversation context. This creates a hybrid voice+keypad interaction model where the agent can prompt "Please enter your account number followed by the pound key" and reliably receive the input.

## Current State

- **Pipecat framework** (v0.0.102) defines `InputDTMFFrame` and `OutputDTMFFrame` with a `KeypadEntry` enum (`0-9`, `*`, `#`). The frame types and plumbing exist.
- **DailyTransport** supports **outbound** DTMF (`send_dtmf`, `_write_dtmf_native`), but does **not** currently generate `InputDTMFFrame` from inbound SIP INFO or RFC 2833 telephone events.
- **No Python code** in the voice agent handles DTMF today. References exist only in design docs for authentication-tool and payment-processing-tool as future dependencies.
- The call-recording-capability idea.md explicitly notes: "DTMF tone capture (not available through the current Daily WebRTC transport)".

## Technical Approach

### Option A: Daily SDK Native DTMF Events (Preferred)

If the Daily SDK exposes (or adds) an `on_dtmf_received` callback for inbound DTMF:

1. **Transport hook** -- Register a callback in `DailyTransport` that maps Daily SDK DTMF events to `InputDTMFFrame(button=KeypadEntry.FIVE)` and pushes them into the pipeline.
2. **DTMFCollectorProcessor** -- A new `FrameProcessor` that sits in the pipeline (after `transport.input()`, parallel to STT) and:
   - Accumulates `InputDTMFFrame` digits into a buffer.
   - Terminates collection on `#` press, timeout (e.g., 5s inter-digit), or reaching a max-length.
   - Emits a `DTMFInputComplete` frame (custom) containing the full digit string.
3. **LLM integration** -- The collected DTMF string is injected into the conversation context as a user message (e.g., `[DTMF input: 1503#]`) or returned as a tool call result if the LLM prompted for keypad entry via a `collect_dtmf` tool.

### Option B: Audio-Based DTMF Detection (Fallback)

If the Daily SDK does not expose inbound DTMF events:

1. **Goertzel-based detector** -- A `FrameProcessor` that analyzes `InputAudioRawFrame` data using the Goertzel algorithm to detect the 8 DTMF frequency pairs (697-1633 Hz).
2. Operates on the raw 8kHz PCM audio before it reaches the STT processor.
3. Same `DTMFCollectorProcessor` accumulation logic as Option A.
4. Trade-off: Adds CPU overhead for tone detection on every audio frame; may conflict with VAD/STT if the caller speaks while pressing keys.

### Pipeline Integration

```
transport.input()
    |
    +---> DTMFDetector/Collector ---> LLM context injection
    |
    +---> STT ---> context_aggregator.user() ---> LLM ---> TTS ---> transport.output()
```

The DTMF path runs in parallel to the STT path. When DTMF collection is active (agent has prompted for keypad input), the STT path may optionally be suppressed to avoid transcribing touch-tone sounds as speech.

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `DTMFCollectorProcessor` | `app/processors/dtmf_collector.py` | Accumulates digits, handles termination |
| `DTMFDetector` (Option B) | `app/processors/dtmf_detector.py` | Goertzel-based tone detection from raw audio |
| `collect_dtmf` tool | `app/tools/builtin/dtmf_tool.py` | LLM tool that activates DTMF collection mode |
| `DTMFObserver` | `app/observers/dtmf_observer.py` | CloudWatch metrics for DTMF events |

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_DTMF_CAPTURE` | `false` | Feature flag to enable DTMF processing |
| `DTMF_INTER_DIGIT_TIMEOUT_MS` | `5000` | Timeout between digits before auto-termination |
| `DTMF_MAX_LENGTH` | `20` | Maximum digits to collect in a single sequence |
| `DTMF_TERMINATOR` | `#` | Key that signals end of input |

## Scope

### In Scope

- Capture inbound DTMF digits from PSTN callers
- Accumulate digits into complete input sequences
- Surface collected digits to the LLM as structured input
- `collect_dtmf` tool so the LLM can prompt for and receive keypad input
- CloudWatch metrics for DTMF events (digits received, collection timeouts, error rate)
- Structured logging for DTMF interactions

### Out of Scope (Future)

- Outbound DTMF generation (already supported by DailyTransport)
- DTMF-based menu trees / IVR flow engine
- Secure DTMF masking in logs (needed for payment-processing-tool)
- Integration with specific tools (authentication, payment) -- those are separate features

## Affected Areas

- **New**: `app/processors/dtmf_collector.py` -- digit accumulation processor
- **New**: `app/tools/builtin/dtmf_tool.py` -- LLM tool for DTMF collection
- **Modified**: `pipeline_ecs.py` -- add DTMF processor to pipeline, register tool
- **Modified**: Observers -- optional `DTMFObserver` for metrics
- **No infrastructure changes** -- runs in existing ECS voice-agent container

## Open Questions

1. **Daily SDK support**: Does the current Daily Python SDK version expose inbound DTMF events? If not, what is the timeline for support, or should we proceed with audio-based detection (Option B)?
2. **STT interference**: When a caller presses keys, the DTMF tones will be picked up by the microphone and sent to STT. Should we mute/suppress STT during active DTMF collection, or filter tone frequencies from the audio stream?
3. **Concurrent input**: Can a caller speak and press keys simultaneously? How should the agent handle mixed voice+DTMF input?
4. **Barge-in behavior**: Should a DTMF keypress during agent speech trigger an interruption (like voice barge-in), or should it be silently buffered?

## Validation Criteria

- [ ] DTMF digits from a PSTN caller are captured and logged correctly
- [ ] Digit accumulation terminates on `#` key or inter-digit timeout
- [ ] LLM can prompt for keypad input and receive the collected digits
- [ ] `collect_dtmf` tool returns the digit string to the LLM context
- [ ] DTMF events emit CloudWatch metrics (digit count, collection duration)
- [ ] Feature is disabled by default (`ENABLE_DTMF_CAPTURE=false`)
- [ ] No impact on existing voice-only call flow when DTMF is disabled
- [ ] Works with both Deepgram (cloud) and SageMaker-hosted STT

## Dependencies

- **Daily SDK** -- Inbound DTMF event support (or fallback to audio detection)
- **Pipecat `InputDTMFFrame`** -- Already defined in v0.0.102
- **tool-calling-framework** (shipped) -- Required for `collect_dtmf` tool registration
- No new Python packages required (Goertzel algorithm is straightforward to implement if needed; or use `dtmf-detector` PyPI package)
