# Fix STT Metrics for SageMaker

| Field    | Value    |
|----------|----------|
| Type     | Bug Fix  |
| Priority | P1       |
| Effort   | Small    |
| Impact   | Medium   |
| Status   | Proposed |

## Problem Statement

After migrating STT from cloud Deepgram WebSocket to SageMaker BiDi streaming (`DeepgramSageMakerSTTService`), the STT metrics observer reports incorrect values across all conversation turns:

- `stt_final_count: 0` — even though final transcripts are clearly reaching the LLM and appearing in conversation logs
- `stt_interim_count: 0` — no interim transcripts counted
- `stt_confidence_avg: null` — no confidence scores captured
- `stt_confidence_min: null` — no minimum confidence captured
- `stt_word_count: null` — no word counts captured
- `stt_latency_ms: null` — no STT latency measured

This was observed on multiple calls after the SageMaker migration (e.g., call `1dc200c0-1bb3-4609-b7d4-46eea448c9dc`). The transcripts are correct and multi-turn conversation works — the issue is purely that the metrics/observability layer is not capturing STT events.

## Evidence

From call `1dc200c0` turn 2 logs:

```
User said: "Yeah. I was wondering if you could check your knowledge base..."
LLM received the text and called search_knowledge_base tool successfully.
Turn metrics: stt_final_count: 0, stt_confidence_avg: null
```

The cloud Deepgram STT service emits `TranscriptionFrame` and `InterimTranscriptionFrame` with confidence scores. The SageMaker variant (`DeepgramSageMakerSTTService` from pipecat) may emit different frame types, or the frames may be missing confidence metadata that the metrics observer expects.

## Likely Root Cause

The metrics observer (or STT quality observer) likely listens for specific frame types or attributes that the `DeepgramSageMakerSTTService` does not emit in the same way as the cloud `DeepgramSTTService`. Possible causes:

1. **Frame type mismatch**: SageMaker STT may emit frames that the observer doesn't recognize or count
2. **Missing confidence field**: The SageMaker STT response format may not include `confidence` in the same structure
3. **Different event flow**: The SageMaker BiDi protocol may not distinguish interim vs. final transcripts the same way

## Suggested Investigation

1. Compare the frame types emitted by `DeepgramSTTService` (cloud) vs `DeepgramSageMakerSTTService` — check if both produce `TranscriptionFrame` / `InterimTranscriptionFrame`
2. Check the STT quality observer's `on_*` handlers to see what frame types it subscribes to
3. Add debug logging to the STT quality observer to trace which frames it receives during a SageMaker call
4. Check if the SageMaker STT response JSON includes confidence scores and whether pipecat parses them

## Impact

- CloudWatch metrics for STT latency and quality are blank/zero — monitoring dashboards are incomplete
- Alarms based on STT metrics will not fire correctly
- Cannot track STT quality degradation in production
- The `poor_audio_turns` metric still works (based on raw audio RMS), but STT-specific quality signals are lost
