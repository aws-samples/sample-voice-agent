---
name: Dashboard Cleanup
type: bug-fix
priority: P1
effort: small
impact: medium
status: idea
created: 2026-02-25
related-to: comprehensive-observability-metrics
---

# Dashboard Cleanup

## Problem Statement

The CloudWatch dashboard has accuracy and relevance issues that make it misleading when operators change the time range selector:

1. **"Calls (Last Hour)" widget** has a hardcoded 1-hour period and a title that doesn't reflect the user's selected time range. SingleValueWidgets with hardcoded periods always show the last fixed-period bucket, not the aggregate across the dashboard's time picker. This creates confusion -- an operator selecting a 24-hour view still sees "Calls (Last Hour)" showing only the most recent 1-hour bucket.

2. **"Avg Call Duration (s)" widget** uses a hardcoded 5-minute period, showing only the last 5-minute average rather than adapting to the selected time range.

3. **Missing tool execution metrics** -- `ToolExecutionTime` and `ToolInvocationCount` are emitted but have no dashboard visualization.

4. **Audio Quality widget** shows only `AudioRMS` Average but not `AudioPeak`, which is emitted and useful for detecting audio clipping.

## Scope

### Fixes

- Replace "Calls (Last Hour)" SingleValueWidget with a GraphWidget titled "Call Volume" that naturally adapts to the dashboard time range
- Replace "Avg Call Duration (s)" SingleValueWidget with a GraphWidget titled "Call Duration" that adapts to the time range
- Both changes ensure the displayed data reflects whatever time period the operator has selected

### Potential Enhancements (Future)

- Add tool execution metrics widget (when tool calling is in broader use)
- Add `AudioPeak` to the Audio Quality widget
- Add active sessions count to the summary row

## Success Criteria

- [ ] Call volume widget reflects the dashboard time range, not a hardcoded period
- [ ] Call duration widget reflects the dashboard time range
- [ ] No widget titles reference a fixed time period that contradicts the dashboard time picker
