---
id: dashboard-cleanup
name: Dashboard Cleanup
type: bug-fix
priority: P1
effort: small
impact: medium
created: 2026-02-25
started: 2026-02-25
shipped: 2026-02-26
---

# Shipped: Dashboard Cleanup

## Summary

Fixed CloudWatch dashboard accuracy and completeness issues. Replaced hardcoded-period SingleValueWidgets with time-range-adaptive GraphWidgets and added missing metric visualizations.

## What Shipped

| # | Item | Status |
|---|------|--------|
| 1 | Replace "Calls (Last Hour)" SingleValueWidget with `Completed Calls` GraphWidget | Done |
| 2 | Replace "Avg Call Duration (s)" SingleValueWidget with `Avg Call Duration` GraphWidget | Done |
| 3 | Remove fixed-time-period titles | Done |
| 4 | Add AudioPeak (Average + Maximum) to Audio Quality widget with clipping headroom annotation | Done |
| 5 | Add Tool Execution Latency widget (Avg/P95/Max) with A2A timeout annotation | Done |
| 6 | Add Tool Invocations widget (Sum per period) | Done |

## Deferred

| # | Item | Reason |
|---|------|--------|
| 1 | Add Active Sessions to Row 1 summary | Enhancement beyond original bug-fix scope. `ActiveCount` already visible in Row 8 via Lambda-emitted `VoiceAgent/Sessions` namespace. Can be added as a follow-up. |

## Files Changed

- `infrastructure/src/constructs/voice-agent-monitoring-construct.ts`

## Quality Gates

### Security Review: PASS

- **Risk Level:** None
- **Findings:** No new IAM permissions, no sensitive data exposure, no injection vectors, no hardcoded secrets. All changes are read-only CloudWatch dashboard widget definitions.
- **Recommendation:** Ship

### QA Validation: PASS

- **Items Verified:** All 3 original success criteria pass (time-range-adaptive widgets, no hardcoded period titles). AudioPeak and Tool Execution widgets verified correct.
- **Test Coverage:** CDK synth validation. No dedicated monitoring construct unit tests (recommended as follow-up).
- **Known Gaps:** Active Sessions Row 1 widget deferred (documented above).
- **Recommendation:** Ship

## Success Criteria (Final)

- [x] Call volume widget reflects the dashboard time range, not a hardcoded period
- [x] Call duration widget reflects the dashboard time range
- [x] No widget titles reference a fixed time period that contradicts the dashboard time picker
- [x] Audio Quality widget shows both AudioRMS and AudioPeak with clipping headroom annotation
- [x] Tool Execution Latency widget shows Avg/P95/Max with A2A timeout annotation
- [x] Tool Invocations widget shows Sum count per period
- [x] All new widgets use Environment dimension and respect the dashboard time picker
