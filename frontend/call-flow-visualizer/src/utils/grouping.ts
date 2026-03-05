import type { CallListItem } from '../types';

export interface DateGroup {
  /** YYYY-MM-DD */
  date: string;
  /** Human-readable label, e.g. "March 5, 2026" */
  label: string;
  /** Calls within this date, already sorted by the active sort */
  calls: CallListItem[];
}

/**
 * Group sorted calls by calendar date.
 * Groups are ordered newest-first regardless of call sort direction,
 * so the most recent day always appears at the top.
 */
export function groupCallsByDate(calls: CallListItem[]): DateGroup[] {
  const groups = new Map<string, CallListItem[]>();

  for (const call of calls) {
    const date = toLocalDateString(call.timestamp);
    if (!groups.has(date)) groups.set(date, []);
    groups.get(date)!.push(call);
  }

  return Array.from(groups.entries())
    .sort(([a], [b]) => b.localeCompare(a)) // newest date first
    .map(([date, dateCalls]) => ({
      date,
      label: formatDateLabel(date),
      calls: dateCalls,
    }));
}

/** Convert a UTC ISO timestamp to a YYYY-MM-DD string in the user's local timezone. */
function toLocalDateString(iso: string): string {
  const d = new Date(iso);
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDateLabel(dateStr: string): string {
  try {
    // Parse as local date to avoid timezone shift
    const parts = dateStr.split('-');
    const year = Number(parts[0]);
    const month = Number(parts[1]);
    const day = Number(parts[2]);
    const d = new Date(year, month - 1, day);
    return d.toLocaleDateString('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return dateStr;
  }
}
