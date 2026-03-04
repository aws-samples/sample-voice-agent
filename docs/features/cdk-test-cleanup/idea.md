# Fix Pre-existing CDK Test Failures

| Field     | Value     |
|-----------|-----------|
| Type      | Tech Debt |
| Priority  | P2        |
| Effort    | Small     |
| Impact    | Medium    |
| Status    | Shipped   |

## Problem Statement

Three CDK infrastructure tests in `infrastructure/test/stacks.test.ts` are failing due to drift between the test assertions and the actual infrastructure code. These failures pre-date the Phase 3 (A2A capability registry) work and are unrelated to it. They reduce CI signal quality and erode developer confidence in the test suite.

## Failing Tests

### 1. `NetworkStack > should create SageMaker Runtime interface endpoint`

**File:** `infrastructure/test/stacks.test.ts:104`

The test asserts `PrivateDnsEnabled: true`, but the VPC construct creates the SageMaker Runtime endpoint with `PrivateDnsEnabled: false`. The implementation was intentionally changed (SageMaker BiDi streaming uses custom endpoint resolution), but the test was not updated.

**Fix:** Update the assertion to expect `PrivateDnsEnabled: false`.

### 2. `EcsStack > should create security group for ECS service`

**File:** `infrastructure/test/stacks.test.ts:293`

The test matches against the pattern `'Security group for Pipecat ECS Service'`, but the actual description is `'Security group for Voice Agent ECS Service - {prefix}'`. The description was renamed when the project was rebranded from "Pipecat" to "Voice Agent", but the test was not updated.

**Fix:** Update the regex pattern to match `'Voice Agent ECS Service'`.

### 3. `EcsStack with KnowledgeBase > should set KB_KNOWLEDGE_BASE_ID environment variable`

**File:** `infrastructure/test/stacks.test.ts:807`

The test asserts that `KB_KNOWLEDGE_BASE_ID` is set as a container environment variable, but the ECS stack reads the KB ID via `ssm.StringParameter.valueFromLookup()` at synth time and does not pass it as an explicit environment variable. The container reads it from SSM at runtime instead.

**Fix:** Either:
- (a) Remove the test if the container reads KB ID from SSM at runtime, or
- (b) Add `KB_KNOWLEDGE_BASE_ID` as an explicit env var in `ecs-stack.ts` if direct injection is preferred

## Scope

- Only test file changes (and possibly one line in `ecs-stack.ts` for the KB env var)
- No infrastructure behavior changes
- No new resources or permissions

## Acceptance Criteria

- All 98 tests in `infrastructure/test/stacks.test.ts` pass (0 failures)
- No changes to deployed infrastructure behavior
