import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listCalls } from '../api/client';
import type { CallListItem } from '../types';
import { formatTime, formatDuration, formatMs, audioQualityLabel } from '../types';

export function CallList() {
  const [calls, setCalls] = useState<CallListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dateFrom, setDateFrom] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const navigate = useNavigate();

  useEffect(() => {
    loadCalls();
  }, [dateFrom]);

  async function loadCalls() {
    setLoading(true);
    setError('');
    try {
      const data = await listCalls({ date_from: dateFrom });
      setCalls(data.calls);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load calls');
    } finally {
      setLoading(false);
    }
  }

  function handleRowClick(callId: string) {
    navigate(`/calls/${encodeURIComponent(callId)}`);
  }

  return (
    <>
      <div className="search-bar">
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
        />
        <button onClick={loadCalls}>Refresh</button>
      </div>

      {loading && <div className="loading">Loading calls...</div>}
      {error && <div className="error">{error}</div>}

      {!loading && !error && (
        <table className="call-list-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Call ID</th>
              <th>Duration</th>
              <th>Turns</th>
              <th>Avg Response</th>
              <th>Audio</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => {
              const audio = audioQualityLabel(call.avg_rms_db);
              return (
                <tr key={call.call_id} onClick={() => handleRowClick(call.call_id)}>
                  <td>{formatTime(call.timestamp)}</td>
                  <td className="mono">{call.call_id.slice(0, 8)}</td>
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
            })}
            {calls.length === 0 && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>
                  No calls found for {dateFrom}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </>
  );
}
