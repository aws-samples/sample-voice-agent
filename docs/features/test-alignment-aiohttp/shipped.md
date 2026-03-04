---
shipped: 2026-01-26
---

# Shipped: Test Alignment for aiohttp Migration

## Summary

Rewrote the test suite to align with the aiohttp-based `service_main.py` implementation, replacing the legacy FastAPI-based tests. Removed dead code that was no longer in use.

## Key Changes

- Created `tests/test_service_main.py` with 23 new tests for aiohttp endpoints
- Deleted `tests/test_main.py` (legacy FastAPI tests)
- Deleted `app/main.py` (legacy FastAPI application - unused)
- Deleted `app/pipeline.py` (legacy pipeline - only used by main.py)
- Added `pytest-aiohttp>=1.0.0` to requirements-dev.txt
- Fixed pre-existing test case in `test_observability.py` (conflicting keyword match)

## Testing

- 74 tests pass (23 new + 51 existing)
- Tests cover:
  - `/health` and `/status` endpoints
  - `/call` endpoint with validation and mocks
  - `PipelineManager` class (start_call, get_status, duplicate handling)
  - Error categorization
  - `PipelineConfig` dataclass from `pipeline_ecs`

## Notes

- Security review passed with no blocking issues
- aiohttp version should be kept >= 3.13.3 to address recent CVEs (advisory only)
- The legacy FastAPI code was completely unused - entrypoint.sh uses `service_main` for SERVICE_MODE
