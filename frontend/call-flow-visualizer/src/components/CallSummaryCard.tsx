import type { CallTimeline } from '../types';
import { formatDateTime, formatDuration, formatMs, audioQualityLabel } from '../types';

interface CallSummaryCardProps {
  timeline: CallTimeline;
}

export function CallSummaryCard({ timeline }: CallSummaryCardProps) {
  const m = timeline.metrics ?? {};
  const audio = audioQualityLabel(m.avg_rms_db as number | undefined);
  const status = timeline.end_status || 'in-progress';

  return (
    <div className="call-summary">
      <div className="summary-header">
        <h2>Call: {timeline.call_id.slice(0, 8)}</h2>
        <span className={`disposition disposition-${status}`}>{status}</span>
      </div>

      <div className="summary-grid">
        <div className="summary-item">
          <label>Started</label>
          <span>{timeline.started_at ? formatDateTime(timeline.started_at) : '-'}</span>
        </div>
        <div className="summary-item">
          <label>Duration</label>
          <span>{formatDuration(timeline.duration_seconds)}</span>
        </div>
        <div className="summary-item">
          <label>Turns</label>
          <span>{timeline.turn_count ?? '-'}</span>
        </div>
        <div className="summary-item">
          <label>Events</label>
          <span>{timeline.event_count}</span>
        </div>
        {m.avg_agent_response_ms != null && (
          <div className="summary-item">
            <label>Avg Response</label>
            <span>{formatMs(m.avg_agent_response_ms as number)}</span>
          </div>
        )}
        {m.interruption_count != null && (
          <div className="summary-item">
            <label>Interruptions</label>
            <span>{String(m.interruption_count)}</span>
          </div>
        )}
        {m.avg_rms_db != null && (
          <div className="summary-item">
            <label>Audio Quality</label>
            <span className={`quality quality-${audio.level}`}>
              {audio.label} ({Number(m.avg_rms_db).toFixed(0)} dB)
            </span>
          </div>
        )}
        {(m.poor_audio_turns as number) > 0 && (
          <div className="summary-item">
            <label>Poor Audio Turns</label>
            <span className="quality quality-poor">
              {String(m.poor_audio_turns)} of {String(timeline.turn_count ?? '?')}
            </span>
          </div>
        )}
      </div>

      <div className="summary-session">
        Session: {timeline.session_id || '-'}
      </div>
    </div>
  );
}
