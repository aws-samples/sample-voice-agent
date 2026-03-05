---
name: Dashboard Call List Sorting & Date Grouping
type: enhancement
priority: P2
effort: small
impact: medium
status: shipped
created: 2026-03-05
related-to: call-flow-visualizer
---

# Dashboard Call List Sorting & Date Grouping

## Problem Statement

The Call Flow Visualizer dashboard displays calls in whatever order the backend API returns them, with no ability to sort by any column. The current layout makes it difficult to find recent calls or compare calls by duration, response time, or turn count. Specific issues:

1. **No sorting** -- The call list table has no sort controls on any column header. The display order is entirely determined by the backend response, which does not guarantee a useful default order. Calls appear in an unintuitive sequence (e.g., 12:30 AM, 11:19 PM, 9:37 PM, 12:04 AM) rather than chronological or reverse-chronological order.

2. **No default sort order** -- There is no explicit ordering; the most natural default for an operator would be latest calls at the top (descending chronological), so the most recent activity is immediately visible without scrolling.

3. **Date selector could be replaced with grouping** -- The current single-date `<input type="date">` picker filters to a specific day, but provides no context for calls across multiple days. Grouping calls by date (with collapsible date headers) would give better context without requiring the user to repeatedly change dates.

## Current Implementation

The call list is rendered in `CallList.tsx` with:
- A plain `<table>` with static `<th>` headers (no click handlers, no sort indicators)
- Calls rendered in API response order via `data.calls.map()`
- A single `<input type="date">` that passes `date_from` to `GET /api/calls`
- No client-side sorting, filtering, or grouping logic

### Affected Files

| File | Change |
|------|--------|
| `frontend/call-flow-visualizer/src/components/CallList.tsx` | Add sort state, column click handlers, sort indicators, date grouping |
| `frontend/call-flow-visualizer/src/styles/timeline.css` | Sortable header styles, date group header styles |
| `frontend/call-flow-visualizer/src/api/client.ts` | Potentially add `sort_by` / `sort_order` query params |

## Proposed Changes

### Column Sorting

- Add clickable column headers with ascending/descending toggle
- Visual sort indicator (arrow) on the active sort column
- Default sort: Time descending (latest calls at top)
- Sortable columns: Time, Duration, Turns, Avg Response, Audio, Status

### Date Grouping (replaces date picker)

- Remove the single-date `<input type="date">` picker
- Load calls for a broader range (e.g., last 7 days, or today by default with a "Load more" option)
- Group calls under date headers (e.g., "March 5, 2026") that act as visual separators
- Consider collapsible date groups so users can focus on a specific day

### Sorting Approach

Client-side sorting is sufficient for the expected call volumes (tens to low hundreds per day). No backend API changes are strictly required, though adding `sort_by` support to the API would be a natural follow-on if call volumes grow.

## Success Criteria

- [ ] Column headers are clickable and toggle sort direction
- [ ] Active sort column shows a directional arrow indicator
- [ ] Default view shows calls sorted by time descending (latest at top)
- [ ] Date picker is removed or replaced with date-grouped display
- [ ] Calls are visually grouped under date headers
