---
started: 2026-01-27
---

# Implementation Plan: CDK Deprecation Cleanup

## Overview

Clean up deprecated CDK API usage to ensure future compatibility, eliminate deployment warnings, and follow current AWS CDK best practices.

## Deprecations to Fix

### 1. containerInsights → containerInsightsV2

**File**: `infrastructure/src/stacks/ecs-stack.ts:112`

**Current** (deprecated):
```typescript
containerInsights: true,
```

**New**:
```typescript
containerInsightsV2: ecs.ContainerInsights.ENHANCED,
```

The `ENHANCED` option provides CloudWatch Container Insights with enhanced observability features.

### 2. logRetention → logGroup

**File**: `infrastructure/src/constructs/session-counter-lambda-construct.ts:72`

**Current** (deprecated):
```typescript
logRetention: logs.RetentionDays.ONE_WEEK,
```

**New**:
```typescript
logGroup: new logs.LogGroup(this, 'SessionCounterLogGroup', {
  logGroupName: `/aws/lambda/${resourcePrefix}-session-counter`,
  retention: logs.RetentionDays.ONE_WEEK,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
}),
```

### 3. url.parse() Node.js deprecation

This warning comes from CDK dependencies, not our code. The `url.parse()` pattern is not present in our codebase - it's an internal CDK/Node.js issue that will be resolved in future CDK releases.

**Action**: No code changes needed. This is a dependency issue.

## Implementation Steps

- [x] Step 1: Update ECS cluster to use `containerInsightsV2`
- [x] Step 2: Update Lambda construct to use explicit `logGroup`
- [x] Step 3: Update test expectations if needed
- [x] Step 4: Deploy and verify deprecation warnings eliminated
- [x] Step 5: Verify CloudWatch Insights and Lambda logs still work

## Files to Modify

| File | Change |
|------|--------|
| `src/stacks/ecs-stack.ts` | Replace `containerInsights` with `containerInsightsV2` |
| `src/constructs/session-counter-lambda-construct.ts` | Replace `logRetention` with `logGroup` |
| `test/stacks.test.ts` | Update test assertion for container insights |

## Technical Decisions

- Use `ContainerInsights.ENHANCED` for better observability (includes additional metrics)
- Create explicit LogGroup resource for better control over log management
- Keep same retention period (1 week) for Lambda logs
- Accept url.parse() warning as it's a dependency issue

## Testing Strategy

1. Run TypeScript compiler to verify no type errors
2. Run existing tests to verify assertions
3. Deploy to staging environment
4. Verify:
   - ECS Container Insights metrics appear in CloudWatch
   - Lambda logs appear in CloudWatch with correct retention
   - No deprecation warnings except the known url.parse() dependency issue

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Container Insights cost increase | ENHANCED provides more metrics but cost is minimal for single cluster |
| Log group naming conflict | Use explicit naming pattern matching Lambda function name |
| Test failures | Update test assertions to match new configuration |

## Progress Log

- 2026-01-27: Plan created
