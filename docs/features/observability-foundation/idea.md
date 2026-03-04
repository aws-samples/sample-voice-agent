---
id: observability-foundation
name: Observability Foundation
type: Enhancement
priority: P1
effort: Small
impact: High
created: 2026-01-26
---

# Observability Foundation

## Problem Statement

Currently, the voice agent pipeline logs basic lifecycle events but lacks the foundation needed for effective debugging and monitoring:

1. **No correlation IDs** - When a call has issues, it's difficult to trace all related log entries across the session. Logs lack a unified identifier to filter by.

2. **No call summary** - When a call ends, there's no consolidated log entry showing key metrics like duration, turn count, or completion status. This makes it hard to quickly assess call outcomes.

3. **Poor error categorization** - Errors are logged with generic messages. There's no categorization (STT vs LLM vs TTS vs transport errors) or tracking of recovery attempts.

## Why This Matters

- **Debugging**: Without correlation IDs, investigating a single call requires manual timestamp correlation across hundreds of log entries
- **Operations**: Without call summaries, there's no quick way to identify failed or problematic calls
- **Reliability**: Without error categorization, it's hard to identify patterns (e.g., "TTS failures spiked at 3pm")

## Proposed Solution

1. **Add Correlation ID**: Generate UUID at call start in `service_main.py`, bind to structlog context
2. **Add Call Summary Logging**: Log duration, turn count, completion status in `_run_pipeline()` finally block
3. **Add Error Categorization**: Create error categories (stt_error, llm_error, tts_error, transport_error) with recovery tracking

## Affected Areas

- backend/voice-agent/app/service_main.py
- backend/voice-agent/app/pipeline_ecs.py
