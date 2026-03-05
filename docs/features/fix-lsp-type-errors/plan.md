---
id: fix-lsp-type-errors
name: Fix LSP Type Errors
type: Tech Debt
priority: P1
effort: Medium
impact: High
status: in_progress
created: 2026-03-05
started: 2026-03-05
---

# Implementation Plan: Fix LSP Type Errors

## Overview

With `pyrightconfig.json` now in place (pointing to `.venv`), running `npx pyright` from `backend/voice-agent/` reports **25 errors, 0 warnings** across 10 files. All import resolution errors are gone -- every remaining error is a real type/logic issue.

| Category | Count | Files |
|----------|-------|-------|
| FlowResult TypedDict mismatches (`reportAssignmentType`) | 5 | 1 |
| SageMaker SDK union attribute access (`reportAttributeAccessIssue`) | 5 | 1 |
| Argument type mismatches (`reportArgumentType`) | 5 | 3 |
| Optional/None member access (`reportOptionalMemberAccess`) | 2 | 2 |
| Async context manager protocol (`reportGeneralTypeIssues`) | 2 | 1 |
| Untyped SDK attribute access (`reportAttributeAccessIssue`) | 3 | 2 |
| Other (float/None, InterimTranscriptionFrame) | 3 | 1 |

## Verification Command

```bash
cd backend/voice-agent
npx pyright
```

Current baseline: **25 errors, 0 warnings**.

## Architecture Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | How to handle Optional narrowing | Explicit `if x is not None` guards + local variables | Preferred over `assert` (stripped by `-O`) and `cast()` (lies to the checker) |
| 2 | Where to use `# type: ignore` | Only when upstream types are wrong or missing stubs | Last resort, always with a comment explaining why |
| 3 | How to fix FlowResult TypedDict mismatches | Replace with `dict[str, Any]` | Result dicts are consumed loosely; `dict[str, Any]` is honest about the actual shape |
| 4 | How to fix InterimTranscriptionFrame type | Widen handler parameter to `Union` type | Both frame types share relevant fields; handler already has `is_final` flag |
| 5 | How to fix untyped third-party libs (aioboto3, smithy SDK) | Targeted `# type: ignore` with explanation | No stubs exist; `cast()` would lie more than `ignore` |

## Phase 0: pyrightconfig.json (DONE)

Created `backend/voice-agent/pyrightconfig.json` pointing to `.venv`. This resolved all 54 import errors plus 7 additional errors that were artifacts of missing type resolution (function monkey-patching, method override, Optional narrowing on `self` attributes).

## Phase 1: Fix Remaining 25 Type Errors

All files are under `backend/voice-agent/`.

### 1.1 -- `app/flows/transitions.py:150,183,198,216,275` -- FlowResult TypedDict mismatches (5 errors)

**Error**: `Type "dict[str, bool | str]" is not assignable to declared type "FlowResult"`

**Root cause**: The `FlowResult` TypedDict (from `pipecat_flows/types.py`) only defines `status: str` and `error: str`. The transfer function assigns dicts with undeclared keys (`message`, `transferred_to`, `reason`, `original_target`, `stayed_in`, `transition_number`) and uses `bool` values for `error` where `str` is expected.

**Fix**: Replace explicit `FlowResult` annotations with `dict[str, Any]`:

```python
result: dict[str, Any] = {
    "error": True,
    "message": "Too many transfers...",
}
```

### 1.2 -- `app/flows/flow_config.py:758` -- List type invariance (1 error)

**Error**: `List[(...) -> Unknown] | None` not assignable to `List[FlowsFunctionSchema | FlowsDirectFunction] | None`

**Root cause**: `_build_global_functions()` returns `List[Callable]`, but `FlowManager.__init__` expects `List[FlowsFunctionSchema | FlowsDirectFunction]`. `List` is invariant.

**Fix**: Change the return type annotation:

```python
def _build_global_functions(...) -> list[FlowsDirectFunction]:
```

### 1.3 -- `app/observability.py:654` -- InterimTranscriptionFrame not assignable (1 error)

**Error**: `"InterimTranscriptionFrame" is not assignable to "TranscriptionFrame"`

**Root cause**: `InterimTranscriptionFrame` and `TranscriptionFrame` are siblings (both extend `TextFrame`), not parent/child.

**Fix**: Widen the handler parameter type:

```python
async def _handle_transcription(
    self,
    frame: Union[TranscriptionFrame, InterimTranscriptionFrame],
    is_final: bool,
) -> None:
```

### 1.4 -- `app/observability.py:702-703` -- dict `.channel` attribute access (2 errors)

**Error**: `Cannot access attribute "channel" for class "dict[Unknown, Unknown]"`

**Root cause**: After `isinstance(result, dict)` check, the fall-through retains `dict` narrowing.

**Fix**: Restructure using `else`:

```python
if isinstance(result, dict):
    # dict path (SageMaker)
    ...
else:
    # Object result (cloud Deepgram STT)
    if hasattr(result, "channel") and result.channel:
        channel = result.channel
        ...
```

### 1.5 -- `app/observability.py:726-727` -- `float | None` passed as `float` (2 errors)

**Error**: `float | None` not assignable to `float` parameter

**Root cause**: `avg_confidence`/`min_confidence` initialized as `None`, conditionally set to `float`. Call happens outside the conditional.

**Fix**: Move the call inside the guard, provide defaults for else:

```python
if self._confidence_scores:
    avg_confidence = sum(self._confidence_scores) / len(self._confidence_scores)
    min_confidence = min(self._confidence_scores)
    self._collector.record_stt_quality(confidence_avg=avg_confidence, confidence_min=min_confidence, ...)
else:
    self._collector.record_stt_quality(confidence_avg=0.0, confidence_min=0.0, ...)
```

### 1.6 -- `app/service_main.py:600` -- `stop_polling` on `Optional` (1 error)

**Error**: `"stop_polling" is not a known attribute of "None"`

**Fix**: Add explicit None guard:

```python
if _a2a_registry is not None:
    await _a2a_registry.stop_polling()
_a2a_registry = None
```

### 1.7 -- `app/services/deepgram_sagemaker_tts.py:360,363-364` -- Stream event attribute access (5 errors)

**Error**: Cannot access `value`/`bytes_` for SDK union event types

**Root cause**: `receive_response()` returns a union of SageMaker BiDi SDK event types. Not all variants have `.value` or `.bytes_`. Runtime `hasattr()` guards are correct but pyright doesn't narrow via `hasattr()`.

**Fix**: Targeted type ignores:

```python
payload = result.value  # type: ignore[union-attr]  # SDK union; guarded by hasattr above

if hasattr(payload, "bytes_") and payload.bytes_:  # type: ignore[union-attr]
    raw_bytes = payload.bytes_  # type: ignore[union-attr]
```

### 1.8 -- `app/services/sagemaker_credentials.py:63` -- List element type mismatch (1 error)

**Error**: `ContainerCredentialsResolver` not assignable to `EnvironmentCredentialsResolver`

**Root cause**: `resolvers` inferred as `list[EnvironmentCredentialsResolver]` from initializer.

**Fix**: Annotate the list broadly:

```python
resolvers: list[Any] = [EnvironmentCredentialsResolver()]
```

### 1.9 -- `app/services/sagemaker_credentials.py:74` -- Dict key type invariance (1 error)

**Error**: `dict[str, SigV4AuthScheme]` not assignable to `dict[ShapeID, AuthScheme[...]]`

**Fix**: Wrap key in `ShapeID()` or use `# type: ignore[arg-type]`:

```python
from smithy_core.shapes import ShapeID
auth_schemes={ShapeID("aws.auth#sigv4"): SigV4AuthScheme(service="sagemaker")}
```

### 1.10 -- `app/session_tracker.py:125` -- `Table` on untyped return (1 error)

**Error**: `Cannot access attribute "Table" for class "_"`

**Fix**: Add type annotation:

```python
_dynamodb_resource: Any = None

def _get_dynamodb() -> Any:
    ...
```

### 1.11 -- `app/tools/builtin/transfer_tool.py:99` -- `sip_refer` on `Optional` (1 error)

**Error**: `"sip_refer" is not a known attribute of "None"`

**Fix**: Add None guard:

```python
if context.transport is None:
    logger.error("transfer_no_transport", call_id=context.call_id)
    await params.result_callback(
        {"error": True, "error_code": "TRANSFER_FAILED", "error_message": "No transport available"}
    )
    return

await context.transport.sip_refer(...)
```

### 1.12 -- `app/a2a/discovery.py:65` -- aioboto3 async context manager (2 errors)

**Error**: `Object of type "_" cannot be used with "async with"`

**Fix**: Targeted type ignore:

```python
async with _session.client(  # type: ignore[reportGeneralTypeIssues]  # aioboto3 untyped
    "servicediscovery", region_name=region
) as client:
```

### 1.13 -- `app/flows/nodes/orchestrator.py:172` -- Function list type mismatch (1 error)

**Error**: `list[(...) -> CoroutineType[...]]` not assignable to `List[Dict | FlowsFunctionSchema | FlowsDirectFunction]`

**Fix**: Cast the list:

```python
functions=cast(list[Any], [transfer])
```

### 1.14 -- `app/flows/nodes/orchestrator.py:174` -- `ContextStrategyConfig | None` not assignable (1 error)

**Error**: `ContextStrategyConfig | None` not assignable to `ContextStrategyConfig`

**Fix**: Conditionally include the key:

```python
node_config: dict[str, Any] = {
    "role_messages": [...],
    "task_messages": [...],
    "functions": [transfer],
    "pre_actions": pre_actions,
}
if context_strategy is not None:
    node_config["context_strategy"] = context_strategy
return NodeConfig(**node_config)
```

### Phase 1 Exit Criteria

- All 25 type errors resolved
- No behavioral changes (runtime logic unchanged)
- Existing tests still pass

## Phase 2: Regression Prevention

### 2.1 -- Add pyright to dev dependencies

Add to `requirements-dev.txt`:

```
pyright>=1.1.400
```

### 2.2 -- Document the zero-error expectation

Add a note to `AGENTS.md` under a new "Type Checking" section:

> All Python code under `backend/voice-agent/app/` must pass `pyright` with zero errors. Run `npx pyright` from `backend/voice-agent/` to verify. Fix any type errors before merging changes.

### Phase 2 Exit Criteria

- pyright is listed as a dev dependency
- Convention is documented

## Files Modified

| File | Change |
|------|--------|
| `backend/voice-agent/pyrightconfig.json` | New file -- pyright configuration (DONE) |
| `backend/voice-agent/app/a2a/discovery.py` | `# type: ignore` for aioboto3 async context manager |
| `backend/voice-agent/app/flows/flow_config.py` | Fix return type for `_build_global_functions()` |
| `backend/voice-agent/app/flows/nodes/orchestrator.py` | Cast function list; conditionally include `context_strategy` |
| `backend/voice-agent/app/flows/transitions.py` | Replace `FlowResult` annotations with `dict[str, Any]` (5 locations) |
| `backend/voice-agent/app/observability.py` | Widen `_handle_transcription` param; restructure `isinstance` branching; fix Optional narrowing |
| `backend/voice-agent/app/service_main.py` | Add None guard for `_a2a_registry` |
| `backend/voice-agent/app/services/deepgram_sagemaker_tts.py` | `# type: ignore` for SDK union types |
| `backend/voice-agent/app/services/sagemaker_credentials.py` | Annotate resolver list; fix `ShapeID` key type |
| `backend/voice-agent/app/session_tracker.py` | Add type annotation to `_get_dynamodb()` |
| `backend/voice-agent/app/tools/builtin/transfer_tool.py` | Add None guard for `context.transport` |
| `backend/voice-agent/requirements-dev.txt` | Add pyright dependency |

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Restructuring `observability.py` branching changes metrics recording | Low | Medium | Existing tests cover this path; verify no metric gaps |
| `pyrightconfig.json` causes false positives with strict mode | Medium | Low | Using `basic` mode; tighten later |
| Upstream pipecat releases new untyped APIs | Medium | Medium | Use `typing.cast()` with explanatory comments as needed |

## Testing Strategy

| Phase | Validation |
|-------|-----------|
| Phase 1 | Run `pytest` to confirm no regressions; run `npx pyright` to confirm 0 errors |
| Phase 2 | Verify `pyright` is installable from dev requirements |

## Success Criteria

| Criteria | Metric |
|----------|--------|
| Zero pyright errors | `npx pyright` exits 0 from `backend/voice-agent/` |
| No runtime regressions | All existing tests pass |
| Convention documented | AGENTS.md updated |
