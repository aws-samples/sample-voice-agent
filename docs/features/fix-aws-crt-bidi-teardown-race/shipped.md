---
id: fix-aws-crt-bidi-teardown-race
name: Fix AWS CRT BiDi Session Teardown Race
type: bug-fix
priority: P3
effort: small
impact: medium
status: shipped
shipped: 2026-02-27
---

# Fix AWS CRT BiDi Session Teardown Race - Shipped

## Summary

Fixed race condition in AWS CRT library during BiDi session teardown that caused `InvalidStateError` tracebacks. The issue occurred when cancelling response tasks while the CRT native layer still had pending callbacks.

## Problem

In `_disconnect()`, calling `self.cancel_task(self._response_task)` sent `CancelledError` into the response loop, which cancelled the `receive_response()` future. The CRT native layer still had pending `_on_body`/`_on_complete` callbacks that tried `set_result()` on now-cancelled futures → `InvalidStateError`.

Error pattern:
```
Exception ignored in: <class 'concurrent.futures._base.InvalidStateError'>
File ".../awscrt/aio/http.py", line 312, in _on_complete
    future.set_result("")
concurrent.futures._base.InvalidStateError: CANCELLED: <Future at ...>
```

## Solution

Reordered `_disconnect()` to:
1. Send protocol close message
2. Close BiDi session first via `close_session()` (sets `is_active=False`)
3. Give response task 2s grace period via `asyncio.wait_for(asyncio.shield(task), timeout=2.0)`
4. Force-cancel only if grace period expires

Also:
- Downgraded `ModelStreamError` during teardown from ERROR to DEBUG level
- Created STT wrapper subclass with same graceful teardown pattern
- Added `RuntimeError` handling for session-not-active cases

## Files Modified

- `app/services/deepgram_sagemaker_tts.py` - Graceful teardown, error handling
- `app/services/deepgram_sagemaker_stt.py` - New wrapper with graceful teardown
- `app/services/factory.py` - Use STT wrapper subclass

## Impact

| Metric | Before | After |
|--------|--------|-------|
| `InvalidStateError` tracebacks | 2-4 per call | 0 |
| `AWS_ERROR_UNKNOWN` | Intermittent | 0 |
| Error-level logs on hangup | Yes | No (downgraded to DEBUG) |

## Testing

- 11 new tests in `test_bidi_teardown.py`
- 454 total tests passing
- SIPp test calls: zero errors, clean teardown

## Related

- [log-noise-cleanup](./log-noise-cleanup/) - Part of comprehensive log cleanup effort
- [log-analysis](./log-analysis/) - Structured logging improvements
