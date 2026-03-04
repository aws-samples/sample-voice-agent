---
id: test-alignment-aiohttp
name: Test Alignment for aiohttp Migration
type: Tech Debt
priority: P1
effort: Medium
impact: High
created: 2026-01-26
---

# Test Alignment for aiohttp Migration

## Problem Statement

The existing test suite references `app.main` (FastAPI-based) but the service has been migrated to use `service_main.py` (aiohttp-based). This mismatch means tests are not accurately validating the current implementation and may be failing or testing outdated code paths.

Key issues:
- Tests import from `app.main` which no longer reflects the production code structure
- Mock configurations may be targeting FastAPI-specific patterns instead of aiohttp
- Test fixtures and helpers may need updating for the new async patterns

## Proposed Solution

Review and update the test suite to align with the aiohttp-based implementation in `service_main.py`.

## Affected Areas
- backend/tests/
- backend/voice-agent/app/service_main.py
- Test fixtures and mocks
- CI/CD pipeline (if tests are currently failing)
