---
id: dashboard-call-list-sorting
name: Dashboard Call List Sorting & Date Grouping
type: enhancement
priority: P2
effort: Small
impact: Medium
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Dashboard Call List Sorting & Date Grouping

## Summary

Added sortable column headers and date-grouped display to the Call Flow Visualizer's call list. Calls now default to newest-first ordering with clickable column headers for ascending/descending sort on timestamp, duration, response time, and turn count. The single-date picker was replaced with a days-back dropdown ("Today", "Last 3 days", "Last 7 days", "Last 30 days") and calls are visually grouped under collapsible date headers.

## What Was Built

### Client-Side Sorting
- `SortColumn`, `SortDirection`, and `SortState` types
- `sortCalls()` utility function with multi-column support
- Default sort: `{ column: 'timestamp', direction: 'desc' }` (newest first)
- Clickable column headers with ascending/descending toggle indicators

### Date Grouping
- `groupCallsByDate()` utility function
- Collapsible date-group headers in the call list
- Replaced single-date picker with days-back dropdown

### Backend API Enhancement
- Added `days_back` parameter to the calls list API endpoint
- Multi-date partition querying for "Last 3/7/30 days" ranges
- Backward compatible with existing `date_from` parameter

### CSS Enhancements
- `.sortable-header` with hover states and cursor pointer
- `.sort-indicator` and `.sort-active` for visual sort direction
- `.date-group-header` for collapsible date sections

## Files Changed

### New Files
- `frontend/call-flow-visualizer/src/utils/sorting.ts` -- sort types and utility
- `frontend/call-flow-visualizer/src/utils/grouping.ts` -- date grouping utility

### Modified Files
- `frontend/call-flow-visualizer/src/types/index.ts` -- sort types
- `frontend/call-flow-visualizer/src/components/CallList.tsx` -- sortable headers, date groups, days-back dropdown
- `frontend/call-flow-visualizer/src/styles/timeline.css` -- sort and group styling
- `frontend/call-flow-visualizer/src/api/client.ts` -- days_back parameter
- `infrastructure/src/functions/call-flow-api/handler.py` -- multi-date partition query

## Quality Gates

### QA Validation: PASS
- Unit tests for sorting and grouping utilities
- All sort columns working with ascending/descending toggle
- Date grouping renders correctly for multi-day ranges
- Backend backward compatible with existing date_from parameter
- Frontend builds cleanly

### Security Review: PASS
- Client-side sorting only -- no new server-side attack surface
- `days_back` parameter validated as integer on backend
- No PII implications
- Existing CORS and access controls unchanged
