---
shipped: 2026-01-27
---

# Shipped: DynamoDB Session Tracking

## Summary

Implemented DynamoDB-based session tracking for voice agent calls, enabling real-time session counting across multiple ECS tasks for auto-scaling decisions while maintaining CloudWatch integration for monitoring dashboards.

## Key Changes

- **DynamoDB Table** (`voice-agent-sessions-{env}`): Tracks sessions with GSI1 for status queries and GSI2 for per-task queries
- **SessionTracker Python Class**: Manages session lifecycle (start → active → ended) with heartbeat mechanism
- **Session Counter Lambda**: Runs every minute to count active sessions and emit CloudWatch metrics
- **ECS Integration**: Automatic session tracking in PipelineManager with TaskId dimension for per-task visibility
- **TTL Cleanup**: Auto-expiring records (24h active, 1h ended, 5min heartbeats)

## Files Created

| File | Purpose |
|------|---------|
| `infrastructure/src/constructs/session-table-construct.ts` | DynamoDB table with GSIs |
| `infrastructure/src/constructs/session-counter-lambda-construct.ts` | Lambda construct |
| `infrastructure/src/functions/session-counter/handler.py` | Lambda code |
| `backend/voice-agent/app/session_tracker.py` | Python SessionTracker class |
| `backend/voice-agent/tests/test_session_tracker.py` | Unit tests (19 tests) |

## Files Modified

- `infrastructure/src/stacks/ecs-stack.ts` - Added table, Lambda, permissions
- `infrastructure/src/ssm-parameters.ts` - Added SESSION_TABLE_* params
- `backend/voice-agent/app/service_main.py` - Integrated SessionTracker
- `backend/voice-agent/app/observability.py` - Added TaskId dimension

## Testing

- **Unit Tests**: 19 new tests for SessionTracker (all passing)
- **Integration Tests**: All 136 Python tests passing
- **Production Verification**:
  - Heartbeats writing to DynamoDB every 30s
  - Lambda counting sessions and emitting CloudWatch metrics
  - Session lifecycle (start → active → ended) verified with live call

## CloudWatch Metrics

New metrics in `VoiceAgent/Sessions` namespace:
- `ActiveCount` - Total active sessions across all tasks
- `HealthyTaskCount` - Tasks with recent heartbeats
- `SessionsPerTask` - Average sessions per healthy task

EMF metrics enhanced with `TaskId` dimension for per-task visibility.

## Bug Fixes During Implementation

- Fixed DynamoDB reserved keyword issue: `TTL` required expression attribute name (`#ttl`)
- Fixed Lambda Decimal serialization: Added `DecimalEncoder` for JSON output

## Notes

- **Required Mode**: Call start fails (HTTP 503) if DynamoDB write fails - ensures accurate counts
- **Cost Estimate**: ~$2-3/month for moderate traffic (10K calls/month)
- Future enhancement: Add auto-scaling rules based on `ActiveCount` metric
