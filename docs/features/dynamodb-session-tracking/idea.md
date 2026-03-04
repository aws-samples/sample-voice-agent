---
name: DynamoDB Session Tracking
priority: P1
effort: Large
added: 2026-01-27
---

# DynamoDB Session Tracking

## Problem Statement

The current voice agent session tracking has limitations:
- In-memory dict is per-task only (no cross-task visibility)
- EMF metrics have 1-2 minute CloudWatch delay
- No aggregate count for scaling decisions
- Session records lost if task crashes

## Proposed Solution

Track sessions in DynamoDB with:
- Real-time writes on session start/end
- Per-task identification via ECS metadata
- GSI for efficient "active session" queries
- Continue EMF emission for CloudWatch dashboards
- Task heartbeats for health monitoring

## Acceptance Criteria

- [ ] DynamoDB table created with GSIs for status and task queries
- [ ] SessionTracker Python class with start/activate/end session methods
- [ ] Heartbeat mechanism for task health monitoring
- [ ] Lambda function to count active sessions and emit CloudWatch metrics
- [ ] Integration with PipelineManager for automatic session tracking
- [ ] TTL-based cleanup for session records
- [ ] Unit tests for SessionTracker

## Dependencies

- ECS stack for container runtime
- CloudWatch for metrics emission

## Notes

This enables real-time session counting for auto-scaling decisions while maintaining CloudWatch integration for dashboards.
