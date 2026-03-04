---
name: Fix Unclosed aiohttp Client Sessions
type: bug-fix
priority: P1
effort: small
impact: medium
status: idea
created: 2026-02-27
related-to: log-noise-cleanup
depends-on: []
---

# Fix Unclosed aiohttp Client Sessions

## Problem Statement

ECS logs show repeated warnings about unclosed `aiohttp.client.ClientSession` objects during call teardown:

```
2026-02-27T19:09:46.428Z
Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x7f7d7d979b80>

Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x7f7d7113e030>

Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x7f7d7113fb30>

Unclosed client session
client_session: <aiohttp.client.ClientSession object at 0x7f7d70906750>
```

These warnings indicate that HTTP client sessions are not being properly closed when the voice agent pipeline shuts down. This is a resource leak that can lead to:

- Connection pool exhaustion over time
- Increased memory usage
- Delayed cleanup of network resources
- Log noise that obscures real issues

## Root Cause Analysis

The unclosed sessions likely stem from one or more of the following:

1. **AWS SDK/Boto3 async clients**: The Bedrock LLM service or other AWS service clients may not be explicitly closing their underlying aiohttp sessions
2. **Pipecat transport layers**: Daily transport or other HTTP-based transports may not properly close sessions during pipeline teardown
3. **A2A capability agent clients**: HTTP clients used for A2A protocol communication may not be properly managed
4. **Missing context manager usage**: Client sessions created without `async with` or explicit `close()` calls

## Proposed Investigation Steps

1. **Identify session creators**: Search codebase for `aiohttp.ClientSession` instantiation and `ClientSession()` calls
2. **Trace lifecycle**: Map which components create sessions and where they should be closed
3. **Check AWS SDK usage**: Review how Bedrock and other AWS clients are initialized and cleaned up
4. **Review pipeline teardown**: Ensure `Pipeline.cleanup()` or equivalent properly closes all HTTP resources

## Proposed Fixes

### Option A: Explicit Session Management (Recommended)

Add explicit session cleanup in the appropriate lifecycle hooks:

```python
# In service shutdown or pipeline cleanup
if hasattr(self, '_http_session') and self._http_session:
    await self._http_session.close()
    self._http_session = None
```

### Option B: Context Manager Pattern

Wrap session usage in async context managers to ensure automatic cleanup:

```python
async with aiohttp.ClientSession() as session:
    # use session
    pass
```

### Option C: AWS SDK Configuration

If AWS SDK is the source, ensure clients are properly closed:

```python
# For aioboto3 or similar
async with session.client('bedrock-runtime') as client:
    # use client
    pass
```

## Files to Investigate

- `backend/voice-agent/app/services/bedrock_llm.py` -- AWS Bedrock client initialization
- `backend/voice-agent/app/pipeline_ecs.py` -- Pipeline setup and teardown
- `backend/voice-agent/app/services/factory.py` -- Service factory, client creation
- `backend/voice-agent/app/capability/` -- A2A HTTP clients
- Any file using `aiohttp.ClientSession` or AWS async clients

## Acceptance Criteria

- [ ] No "Unclosed client session" warnings in ECS logs during normal call teardown
- [ ] All HTTP client sessions are properly closed when pipeline shuts down
- [ ] No regression in call functionality or performance
- [ ] Memory usage remains stable over long-running deployments

## Estimated Effort

Small: 1-2 hours to identify and fix the session leak.
