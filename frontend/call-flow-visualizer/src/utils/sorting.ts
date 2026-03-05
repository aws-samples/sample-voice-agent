import type { CallListItem, SortColumn, SortDirection } from '../types';

/**
 * Sort calls by the given column and direction.
 * Null/undefined values always sort last regardless of direction.
 */
export function sortCalls(
  calls: CallListItem[],
  column: SortColumn,
  direction: SortDirection,
): CallListItem[] {
  const dir = direction === 'asc' ? 1 : -1;

  return [...calls].sort((a, b) => {
    const aVal = a[column];
    const bVal = b[column];

    // Nulls always sort last
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return 1;
    if (bVal == null) return -1;

    // String comparison for status and timestamp (ISO strings sort lexically)
    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return aVal.localeCompare(bVal) * dir;
    }

    // Numeric comparison
    return ((aVal as number) - (bVal as number)) * dir;
  });
}
