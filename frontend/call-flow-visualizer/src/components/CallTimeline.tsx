import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getCallTimeline } from '../api/client';
import { TimelineEvent } from './TimelineEvent';
import { CallSummaryCard } from './CallSummaryCard';
import type { CallTimeline } from '../types';

export function CallTimelineView() {
  const { callId } = useParams<{ callId: string }>();
  const [timeline, setTimeline] = useState<CallTimeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!callId) return;
    setLoading(true);
    getCallTimeline(callId)
      .then(setTimeline)
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load timeline'))
      .finally(() => setLoading(false));
  }, [callId]);

  if (loading) return <div className="loading">Loading timeline...</div>;
  if (error) return <div className="error">{error}</div>;
  if (!timeline) return <div className="error">No data</div>;

  const hasTranscripts = timeline.events.some(
    (e) => e.event_type === 'conversation_turn'
  );

  // Calculate relative timestamps from first event
  const firstTs = timeline.events[0]?.timestamp
    ? new Date(timeline.events[0].timestamp).getTime()
    : 0;

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Link to="/">&larr; Back to calls</Link>
      </div>

      <CallSummaryCard timeline={timeline} />

      {!hasTranscripts && (
        <div className="banner-warning">
          Transcript logging was not enabled for this call. Showing system
          events and latency data only. Enable with
          ENABLE_CONVERSATION_LOGGING=true.
        </div>
      )}

      <div className="timeline">
        {timeline.events.map((event, i) => (
          <TimelineEvent key={i} event={event} baseTimestamp={firstTs} />
        ))}
      </div>
    </>
  );
}
