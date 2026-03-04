---
name: Fix AWS CRT BiDi Session Teardown Race
type: bug
priority: P3
effort: small
impact: low
status: completed
created: 2026-02-23
shipped: 2026-02-27
related-to: deepgram-sagemaker-bidirectional-streaming
depends-on: []
---

# Fix AWS CRT BiDi Session Teardown Race

## Problem Statement

During call teardown, the AWS CRT HTTP library throws `InvalidStateError` exceptions when BiDi (bidirectional streaming) sessions for SageMaker STT/TTS are being closed:

```
Exception ignored in: <class 'concurrent.futures._base.InvalidStateError'>
Traceback (most recent call last):
  File "/usr/local/lib/python3.12/site-packages/awscrt/aio/http.py", line 312, in _on_complete
    future.set_result("")
concurrent.futures._base.InvalidStateError: CANCELLED: <Future at 0x7fc45fd70500 state=cancelled>

Traceback (most recent call last):
  File "/usr/local/lib/python3.12/site-packages/awscrt/aio/http.py", line 298, in _on_body
    future.set_result(chunk)
concurrent.futures._base.InvalidStateError: CANCELLED: <Future at 0x7fc4a16aeff0 state=cancelled>

Treating Python exception as error 3(AWS_ERROR_UNKNOWN)
```

Observed during a live call on 2026-02-23. The exceptions are "ignored" by Python (not propagated), so they don't affect call functionality. However, they produce noisy error logs and the `AWS_ERROR_UNKNOWN` line.

## Root Cause

This is a race condition in the AWS CRT library's HTTP streaming implementation. When a BiDi session is torn down:

1. The application cancels the streaming future (e.g., by closing the connection)
2. The CRT's native layer still has pending callbacks (`_on_body`, `_on_complete`)
3. These callbacks try to `set_result()` on the already-cancelled future
4. Python raises `InvalidStateError` because you can't set a result on a `CANCELLED` future

The race is between the Python-side future cancellation and the native CRT callbacks firing. This is a known pattern with AWS CRT + asyncio.

## Impact

- **No functional impact**: Exceptions are ignored, calls work fine
- **Log noise**: 2-4 error lines per call teardown
- **Potential confusion**: Operators reviewing logs may mistake these for real errors

## Proposed Solutions

### Option A: Graceful BiDi session close (recommended)

In `sagemaker_credentials.py` or the BiDi client wrapper, ensure the streaming session is closed gracefully before cancelling futures:

1. Send a close/end-of-stream signal to the BiDi endpoint
2. Wait briefly for the CRT to acknowledge
3. Then cancel/close the connection

### Option B: Suppress at logging level

Add a filter to suppress `InvalidStateError` from `awscrt.aio.http` during shutdown. This is a band-aid but eliminates the log noise.

### Option C: Upstream fix

Check if newer versions of `awscrt` or `aws-crt-python` have fixed this race. If not, consider filing an issue.

## Files to Investigate

- `backend/voice-agent/app/services/sagemaker_credentials.py` -- BiDi client initialization and credential patching
- `backend/voice-agent/app/services/deepgram_sagemaker_tts.py` -- TTS BiDi session lifecycle
- Pipecat source: `pipecat/services/deepgram/stt_sagemaker.py` -- STT BiDi session lifecycle
- Pipecat source: `pipecat/services/aws/sagemaker/bidi_client.py` -- Low-level BiDi client

## Estimated Effort

Small -- ~1-2 hours for Option A or B. Option C depends on upstream.

## Resolution

Implemented **Option A: Graceful BiDi session close** for both STT and TTS services.

### Root Cause (detailed)

In `_disconnect()`, pipecat's upstream code calls `cancel_task(response_task)` which sends `CancelledError` into the response loop. This cancels the `receive_response()` future. The CRT native HTTP/2 layer still has pending `_on_body`/`_on_complete` callbacks (in `awscrt/aio/http.py` lines 298, 312) that try `set_result()` on these now-cancelled futures, raising `InvalidStateError`.

### Fix

Reordered `_disconnect()` in both services to:

1. Send protocol-level close message (`{"type": "Close"}` for TTS, `{"type": "CloseStream"}` for STT)
2. **Close the BiDi session first** via `close_session()` — sets `is_active=False` and closes the input stream, signaling the CRT to drain
3. Give the response task a 2s grace period to exit naturally via `asyncio.wait_for(asyncio.shield(task), timeout=2.0)`
4. Only force-cancel via `cancel_task()` if the grace period expires

Also added `RuntimeError` handling in the TTS response processor for the expected "BiDi session not active" error that occurs when `receive_response()` is called after `close_session()`.

### Files Changed

- `backend/voice-agent/app/services/deepgram_sagemaker_tts.py` — Reordered `_disconnect()`, added `RuntimeError` handler in `_process_responses()`
- `backend/voice-agent/app/services/deepgram_sagemaker_stt.py` — **New file**: thin subclass of pipecat's `DeepgramSageMakerSTTService` that overrides `_disconnect()` with the same graceful pattern
- `backend/voice-agent/app/services/factory.py` — Import STT from our wrapper instead of pipecat directly
- `backend/voice-agent/tests/test_bidi_teardown.py` — **New file**: 9 tests covering teardown ordering, grace period, force-cancel, and method override

### Verification

Deployed and tested with SIPp call. CloudWatch logs show zero `InvalidStateError`, zero `AWS_ERROR_UNKNOWN`, zero tracebacks during call teardown.
