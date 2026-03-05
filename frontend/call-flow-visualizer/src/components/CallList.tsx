import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { listCalls } from '../api/client';
import type { CallListItem, SortColumn, SortState } from '../types';
import { formatTime, formatDuration, formatMs, audioQualityLabel } from '../types';
import { sortCalls } from '../utils/sorting';
import { groupCallsByDate } from '../utils/grouping';

const DAYS_BACK_OPTIONS = [
  { value: 1, label: 'Today' },
  { value: 3, label: 'Last 3 days' },
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
];

const COLUMNS: { key: SortColumn; label: string }[] = [
  { key: 'timestamp', label: 'Time' },
  { key: 'duration_seconds', label: 'Duration' },
  { key: 'turn_count', label: 'Turns' },
  { key: 'avg_response_ms', label: 'Avg Response' },
  { key: 'avg_rms_db', label: 'Audio' },
  { key: 'status', label: 'Status' },
];

/** Default column direction when first clicking a column header. */
function defaultDirection(column: SortColumn): 'asc' | 'desc' {
  // Time defaults descending (newest first); everything else ascending
  return column === 'timestamp' ? 'desc' : 'asc';
}

export function CallList() {
  const [calls, setCalls] = useState<CallListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [daysBack, setDaysBack] = useState(7);
  const [sortState, setSortState] = useState<SortState>({
    column: 'timestamp',
    direction: 'desc',
  });
  const [collapsedDates, setCollapsedDates] = useState<Set<string>>(new Set());
  const navigate = useNavigate();

  const loadCalls = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await listCalls({ days_back: daysBack });
      setCalls(data.calls);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load calls');
    } finally {
      setLoading(false);
    }
  }, [daysBack]);

  useEffect(() => {
    loadCalls();
  }, [loadCalls]);

  const sortedCalls = useMemo(
    () => sortCalls(calls, sortState.column, sortState.direction),
    [calls, sortState],
  );

  const dateGroups = useMemo(
    () => groupCallsByDate(sortedCalls),
    [sortedCalls],
  );

  function handleSort(column: SortColumn) {
    setSortState((prev) => {
      if (prev.column === column) {
        // Toggle direction
        return { column, direction: prev.direction === 'asc' ? 'desc' : 'asc' };
      }
      return { column, direction: defaultDirection(column) };
    });
  }

  function toggleDateGroup(date: string) {
    setCollapsedDates((prev) => {
      const next = new Set(prev);
      if (next.has(date)) {
        next.delete(date);
      } else {
        next.add(date);
      }
      return next;
    });
  }

  function handleRowClick(callId: string) {
    navigate(`/calls/${encodeURIComponent(callId)}`);
  }

  function sortIndicator(column: SortColumn): string {
    if (sortState.column !== column) return '\u2195'; // ↕ both arrows
    return sortState.direction === 'asc' ? '\u2191' : '\u2193'; // ↑ or ↓
  }

  return (
    <>
      <div className="search-bar">
        <select
          value={daysBack}
          onChange={(e) => setDaysBack(Number(e.target.value))}
        >
          {DAYS_BACK_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <button onClick={loadCalls}>Refresh</button>
      </div>

      {loading && <div className="loading">Loading calls...</div>}
      {error && <div className="error">{error}</div>}

      {!loading && !error && (
        <table className="call-list-table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  className={`sortable-header${sortState.column === col.key ? ' sort-active' : ''}`}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}
                  <span className="sort-indicator">{sortIndicator(col.key)}</span>
                </th>
              ))}
              {/* Call ID column - not sortable */}
            </tr>
          </thead>
          <tbody>
            {dateGroups.length === 0 && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
                  No calls found
                </td>
              </tr>
            )}
            {dateGroups.map((group) => {
              const isCollapsed = collapsedDates.has(group.date);
              return (
                <CallDateGroup
                  key={group.date}
                  label={group.label}
                  callCount={group.calls.length}
                  collapsed={isCollapsed}
                  onToggle={() => toggleDateGroup(group.date)}
                >
                  {!isCollapsed &&
                    group.calls.map((call) => (
                      <CallRow
                        key={call.call_id}
                        call={call}
                        onClick={() => handleRowClick(call.call_id)}
                      />
                    ))}
                </CallDateGroup>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────────────

function CallDateGroup({
  label,
  callCount,
  collapsed,
  onToggle,
  children,
}: {
  label: string;
  callCount: number;
  collapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <>
      <tr
        className={`date-group-header${collapsed ? ' collapsed' : ''}`}
        onClick={onToggle}
      >
        <td colSpan={6}>
          <span className="collapse-icon">{collapsed ? '\u25B6' : '\u25BC'}</span>
          {label}
          <span className="date-group-count">{callCount} call{callCount !== 1 ? 's' : ''}</span>
        </td>
      </tr>
      {children}
    </>
  );
}

function CallRow({ call, onClick }: { call: CallListItem; onClick: () => void }) {
  const audio = audioQualityLabel(call.avg_rms_db);
  return (
    <tr onClick={onClick}>
      <td>
        <span className="call-time">{formatTime(call.timestamp)}</span>
        <span className="call-id mono">{call.call_id.slice(0, 8)}</span>
      </td>
      <td>{formatDuration(call.duration_seconds)}</td>
      <td>{call.turn_count ?? '-'}</td>
      <td>{formatMs(call.avg_response_ms)}</td>
      <td>
        <span className={`quality quality-${audio.level}`}>
          {audio.label}
        </span>
      </td>
      <td>
        <span className={`disposition disposition-${call.status ?? 'unknown'}`}>
          {call.status ?? 'unknown'}
        </span>
      </td>
    </tr>
  );
}
