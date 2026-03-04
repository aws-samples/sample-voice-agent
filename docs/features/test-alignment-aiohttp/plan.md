---
started: 2026-01-26
---

# Implementation Plan: Test Alignment for aiohttp Migration

## Overview

Rewrite `test_main.py` to test the aiohttp-based `service_main.py` instead of the legacy FastAPI `app.main`. This involves migrating from FastAPI's synchronous TestClient to aiohttp's async test utilities, updating endpoint paths, and aligning mock patterns with the current implementation.

## Analysis Summary

| Aspect | Current Tests | Production Code | Change Required |
|--------|---------------|-----------------|-----------------|
| Framework | FastAPI | aiohttp | Migrate test client |
| Test Client | `fastapi.testclient.TestClient` | N/A | Use `aiohttp.test_utils.AioHTTPTestCase` |
| Endpoints | `/ping`, `/start`, `/sessions` | `/health`, `/status`, `/call` | Update paths |
| Import Path | `from app.main import app` | `from app.service_main import create_app` | Update imports |
| Mock Target | `app.main.create_voice_pipeline` | `app.pipeline_ecs.create_voice_pipeline` | Update patch paths |
| Session State | `active_sessions` module-level | `pipeline_manager.active_sessions` | Update state access |
| Request Models | `SessionRequest` (Pydantic) | Raw JSON parsing | Remove model tests |

## Implementation Steps

- [x] Step 1: Create new test file structure
  - Rename `test_main.py` to `test_main_legacy.py` (preserve for reference)
  - Create new `test_service_main.py` for aiohttp tests

- [x] Step 2: Set up aiohttp test infrastructure
  - Create async test fixtures using `pytest-aiohttp`
  - Set up `AioHTTPTestCase` or use `aiohttp.test_utils.TestClient`
  - Configure environment variables for tests

- [x] Step 3: Migrate health check tests
  - Update endpoint from `/ping` to `/health`
  - Verify response structure matches `PipelineManager.get_status()`
  - Test async response handling

- [x] Step 4: Migrate session management tests (call endpoint)
  - Update endpoint from `/start` to `/call`
  - Update mock target from `app.main.create_voice_pipeline` to `app.pipeline_ecs.create_voice_pipeline`
  - Test required fields validation (room_url, room_token, session_id)
  - Test successful call initiation

- [x] Step 5: Migrate status endpoint tests
  - Update endpoint from `/sessions` to `/status`
  - Verify response includes `active_sessions` count and `session_ids`

- [x] Step 6: Update PipelineManager tests
  - Test `start_call()` method directly
  - Test `get_status()` method
  - Test duplicate session handling

- [x] Step 7: Remove obsolete tests
  - Remove `SessionRequest` Pydantic model tests (no longer used)
  - Remove `/sessions/{id}` DELETE endpoint tests (endpoint removed)
  - Update `PipelineConfig` tests to use `pipeline_ecs.PipelineConfig`

- [x] Step 8: Verify test coverage
  - Run pytest with coverage
  - Ensure all handlers in service_main.py are tested
  - Verify error handling paths

## Technical Decisions

1. **Test Framework**: Use `pytest-aiohttp` for async test support rather than `AioHTTPTestCase` for consistency with existing async tests
2. **Fixture Approach**: Create `aiohttp_client` fixture that returns test client for `create_app()`
3. **Mock Strategy**: Patch at import location (`app.pipeline_ecs.create_voice_pipeline`) not definition location
4. **State Isolation**: Use fresh `PipelineManager` instance per test via fixture

## Testing Strategy

**Unit Tests:**
- `handle_health()` - health check response
- `handle_status()` - status response with session counts
- `handle_call()` - call initiation with various inputs

**Integration Tests:**
- Full request/response cycle through aiohttp app
- Error handling for malformed requests
- JSON parsing validation

**Async Tests:**
- Use `@pytest.mark.asyncio` decorator
- Test concurrent call handling
- Test cancellation handling

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing CI | Keep legacy tests until new tests pass |
| Missing test scenarios | Compare coverage before/after migration |
| Async test timing issues | Use proper async fixtures, avoid `sleep()` |
| Mock leakage between tests | Use fresh fixtures per test |

## Dependencies

- `pytest-aiohttp>=1.0.0` - Add to requirements-dev.txt if not present
- `aiohttp>=3.9.0` - Already in requirements.txt

## File Changes

| File | Action |
|------|--------|
| `tests/test_main.py` | Rename to `test_main_legacy.py` |
| `tests/test_service_main.py` | Create (new aiohttp tests) |
| `requirements-dev.txt` | Add `pytest-aiohttp` if missing |
