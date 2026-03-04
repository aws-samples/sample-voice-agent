# Implementation Plan: DynamoDB Session Tracking

## Overview

Add DynamoDB-based session tracking to enable real-time accurate session counts across multiple ECS tasks, supporting auto-scaling decisions while maintaining CloudWatch integration for dashboards.

## DynamoDB Table Schema

**Table Name:** `voice-agent-sessions-{environment}`

| Key | Format | Purpose |
|-----|--------|---------|
| PK | `SESSION#{session_id}` or `TASK#{task_id}` | Partition by session or task |
| SK | `METADATA` or `HEARTBEAT` | Item type |

**Attributes:**
- `session_id`, `call_id`, `task_id`
- `status`: "starting" → "active" → "ended"
- `end_status`: "completed", "cancelled", "error"
- `started_at`, `updated_at`, `ended_at` (epoch timestamps)
- `turn_count`, `error_category`
- `TTL`: Auto-cleanup (24h for active, 1h for ended, 5min for heartbeats)

**GSI1 (Query active sessions):**
- GSI1PK: `STATUS#{status}`
- GSI1SK: `{timestamp}#{session_id}`

**GSI2 (Query by task):**
- GSI2PK: `TASK#{task_id}`
- GSI2SK: `{timestamp}#{session_id}`

## Implementation Steps

### Phase 1: Infrastructure (CDK)
- [x] Create `session-table-construct.ts` with DynamoDB table
- [x] Create `session-counter-lambda-construct.ts` with Lambda function
- [x] Create Lambda handler code (`handler.py`)
- [x] Update SSM parameters with table name/ARN
- [x] Update constructs index exports

### Phase 2: Python Session Tracker
- [x] Create `session_tracker.py` with SessionTracker class
- [x] Implement `start_session()`, `activate_session()`, `end_session()`
- [x] Implement `heartbeat()` and `start_heartbeat_loop()`
- [x] Add `get_ecs_task_id()` helper
- [x] Add exponential backoff retry (3 attempts)

### Phase 3: Integration
- [x] Update `ecs-stack.ts` to include session table and Lambda
- [x] Grant DynamoDB permissions to ECS task role
- [x] Add `SESSION_TABLE_NAME` environment variable
- [x] Integrate SessionTracker with PipelineManager
- [x] Add TaskId dimension to EMF session health metrics

### Phase 4: Testing
- [x] Create unit tests for SessionTracker
- [x] Deploy and verify heartbeats in DynamoDB
- [x] Verify Lambda session counting
- [x] Verify CloudWatch metrics emission

## Files Created/Modified

### New Files
- `infrastructure/src/constructs/session-table-construct.ts`
- `infrastructure/src/constructs/session-counter-lambda-construct.ts`
- `infrastructure/src/functions/session-counter/handler.py`
- `infrastructure/src/functions/session-counter/requirements.txt`
- `backend/voice-agent/app/session_tracker.py`
- `backend/voice-agent/tests/test_session_tracker.py`

### Modified Files
- `infrastructure/src/stacks/ecs-stack.ts`
- `infrastructure/src/constructs/index.ts`
- `infrastructure/src/ssm-parameters.ts`
- `backend/voice-agent/app/service_main.py`
- `backend/voice-agent/app/observability.py`

## Design Decisions

- **Tracking Mode:** Required - call start fails if DynamoDB write fails
- **Heartbeat Interval:** 30 seconds
- **TTL Values:** 24h active, 1h ended, 5min heartbeats
- **Retry:** 3 attempts with exponential backoff (100ms, 200ms, 400ms)

## Progress Log

- 2026-01-27: Plan created and approved
- 2026-01-27: All implementation phases completed
- 2026-01-27: Deployed and verified in production
- 2026-01-27: Fixed TTL reserved keyword issue in end_session
