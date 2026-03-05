import { useState } from 'react';
import type { CallEvent } from '../types';
import { getEventColor, formatMs } from '../types';

function formatRelativeTime(eventTs: string, baseTs: number): string {
  const ms = new Date(eventTs).getTime() - baseTs;
  if (ms < 0) return '00:00.0';
  const totalSeconds = ms / 1000;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(1).padStart(4, '0')}`;
}

function formatEventLabel(event: CallEvent): string {
  switch (event.event_type) {
    case 'session_started':
      return 'Call Started';
    case 'session_ended':
      return 'Call Ended';
    case 'conversation_turn': {
      const speaker = event.data?.speaker === 'user' ? 'Caller' : 'Agent';
      const agentNode = event.data?.agent_node ? ` [${String(event.data.agent_node)}]` : '';
      return event.data?.speaker === 'user' ? speaker : `${speaker}${agentNode}`;
    }
    case 'turn_completed':
      return `Turn ${event.turn_number ?? '?'} Metrics`;
    case 'tool_execution':
      return `Tool: ${String(event.data?.tool_name ?? 'unknown')}`;
    case 'barge_in':
      return 'Caller Interrupted';
    case 'call_metrics_summary':
      return 'Call Summary';
    case 'poor_audio_detected':
      return 'Low Audio Volume';
    case 'audio_clipping_detected':
      return 'Audio Clipping';
    case 'a2a_tool_call_start':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (started)`;
    case 'a2a_tool_call_success':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (success)`;
    case 'a2a_tool_call_cache_hit':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (cached)`;
    case 'a2a_tool_call_timeout':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (timeout)`;
    case 'a2a_tool_call_error':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (error)`;
    case 'agent_transition':
      return `Transition: ${String(event.data?.from_node ?? '?')} \u2192 ${String(event.data?.to_node ?? '?')}`;
    case 'flow_a2a_call_start':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (started)`;
    case 'flow_a2a_call_success':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (success)`;
    case 'flow_a2a_call_error':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (error)`;
    case 'flow_a2a_call_timeout':
      return `${_friendlySkillName(String(event.data?.skill_id ?? 'unknown'))} (timeout)`;
    default:
      return event.event_type.replace(/_/g, ' ');
  }
}

/** "search_knowledge_base" → "Knowledge Base" */
function _friendlySkillName(skillId: string): string {
  return skillId
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderEventContent(event: CallEvent): JSX.Element | string {
  const d = event.data ?? {};
  switch (event.event_type) {
    case 'conversation_turn':
      return String(d.content ?? '');

    case 'turn_completed':
      return <TurnMetrics data={d} />;

    case 'tool_execution':
      return (
        <span>
          <span className={`inline-status status-${d.status}`}>{String(d.status ?? '?')}</span>
          {' in '}{formatMs(d.execution_time_ms as number)}
          {d.category ? <span className="meta"> [{String(d.category)}]</span> : ''}
          {d.result_summary ? <span className="result-preview"> {String(d.result_summary).slice(0, 120)}{String(d.result_summary).length > 120 ? '...' : ''}</span> : ''}
        </span>
      );

    case 'session_ended':
      return (
        <span>
          <span className={`inline-status status-${d.end_status}`}>{String(d.end_status ?? 'unknown')}</span>
          {d.turn_count != null && <span className="meta"> | {String(d.turn_count)} turns</span>}
        </span>
      );

    case 'call_metrics_summary':
      return <CallMetricsSummary data={d} />;

    case 'poor_audio_detected': {
      const db = Number(d.avg_rms_db ?? 0).toFixed(0);
      return (
        <span>
          Caller mic level was <strong>{db} dB</strong> (threshold: -55 dB).
          <span className="meta"> Common with speakerphone or noisy line.</span>
        </span>
      );
    }

    case 'audio_clipping_detected':
      return 'Audio signal was clipped — microphone volume may be too high.';

    case 'barge_in':
      return `Caller interrupted the agent at turn ${event.turn_number ?? '?'}`;

    case 'a2a_tool_call_start':
      return d.query
        ? <span>Query: <em>&ldquo;{String(d.query)}&rdquo;</em></span>
        : '';

    case 'a2a_tool_call_success':
      return (
        <span>
          Completed in {formatMs(d.elapsed_ms as number)}
          {d.response_length != null && <span className="meta"> | {String(d.response_length)} chars returned</span>}
          {d.result_summary ? <span className="result-preview"> {String(d.result_summary).slice(0, 120)}{String(d.result_summary).length > 120 ? '...' : ''}</span> : ''}
        </span>
      );

    case 'a2a_tool_call_cache_hit':
      return `Cache hit in ${formatMs(d.cache_ms as number)}`;

    case 'a2a_tool_call_timeout':
      return `Timed out after ${formatMs(d.elapsed_ms as number)}`;

    case 'a2a_tool_call_error':
      return `Error: ${String(d.error ?? 'unknown')}`;

    case 'agent_transition':
      return (
        <span>
          {d.reason ? <em>&ldquo;{String(d.reason)}&rdquo;</em> : ''}
          {d.transition_latency_ms != null && <span className="meta"> | transition {formatMs(d.transition_latency_ms as number)}</span>}
          {d.summary_latency_ms != null && <span className="meta"> | summary {formatMs(d.summary_latency_ms as number)}</span>}
          {d.loop_protection === true && <span className="inline-status status-error">loop protection</span>}
        </span>
      );

    case 'flow_a2a_call_start':
      return d.query
        ? <span>Query: <em>&ldquo;{String(d.query)}&rdquo;</em></span>
        : '';

    case 'flow_a2a_call_success':
      return (
        <span>
          Completed in {formatMs(d.elapsed_ms as number)}
          {d.response_length != null && <span className="meta"> | {String(d.response_length)} chars returned</span>}
          {d.result_summary ? <span className="result-preview"> {String(d.result_summary).slice(0, 120)}{String(d.result_summary).length > 120 ? '...' : ''}</span> : ''}
        </span>
      );

    case 'flow_a2a_call_error':
      return `Error: ${String(d.error ?? 'unknown')}`;

    case 'flow_a2a_call_timeout':
      return `Timed out after ${formatMs(d.elapsed_ms as number)}`;

    case 'session_started':
      return '';

    default:
      return '';
  }
}

// ── Sub-components for rich event content ──────────────────────────

function TurnMetrics({ data }: { data: Record<string, unknown> }) {
  const e2e = data.agent_response_latency_ms as number | undefined;
  const rms = data.audio_rms_db as number | undefined;
  const confidence = data.stt_confidence_avg as number | undefined;
  const speakingMs = data.user_speaking_duration_ms as number | undefined;
  const silenceMs = data.silence_duration_ms as number | undefined;
  const gapMs = data.turn_gap_ms as number | undefined;

  return (
    <div className="turn-metrics">
      {e2e != null && (
        <div className="metric-chip">
          <span className="metric-label">Response</span>
          <span className={`metric-value ${_latencyClass(e2e)}`}>{formatMs(e2e)}</span>
        </div>
      )}
      {confidence != null && (
        <div className="metric-chip">
          <span className="metric-label">STT</span>
          <span className="metric-value">{(confidence * 100).toFixed(1)}%</span>
        </div>
      )}
      {rms != null && (
        <div className="metric-chip">
          <span className="metric-label">Audio</span>
          <span className={`metric-value ${_audioClass(rms)}`}>{rms.toFixed(0)} dB</span>
        </div>
      )}
      {speakingMs != null && (
        <div className="metric-chip">
          <span className="metric-label">Spoke</span>
          <span className="metric-value">{formatMs(speakingMs)}</span>
        </div>
      )}
      {gapMs != null && (
        <div className="metric-chip">
          <span className="metric-label">Gap</span>
          <span className="metric-value">{formatMs(gapMs)}</span>
        </div>
      )}
      {silenceMs != null && Number(silenceMs) > 3000 && (
        <div className="metric-chip">
          <span className="metric-label">Silence</span>
          <span className="metric-value">{formatMs(silenceMs)}</span>
        </div>
      )}
    </div>
  );
}

function CallMetricsSummary({ data }: { data: Record<string, unknown> }) {
  const dur = data.duration_seconds as number | undefined;
  const turns = data.turn_count as number | undefined;
  const avgResp = data.avg_agent_response_ms as number | undefined;
  const interrupts = data.interruption_count as number | undefined;
  const poorTurns = data.poor_audio_turns as number | undefined;
  const rms = data.avg_rms_db as number | undefined;

  return (
    <div className="turn-metrics">
      {dur != null && (
        <div className="metric-chip">
          <span className="metric-label">Duration</span>
          <span className="metric-value">{Math.round(dur)}s</span>
        </div>
      )}
      {turns != null && (
        <div className="metric-chip">
          <span className="metric-label">Turns</span>
          <span className="metric-value">{String(turns)}</span>
        </div>
      )}
      {avgResp != null && (
        <div className="metric-chip">
          <span className="metric-label">Avg Response</span>
          <span className={`metric-value ${_latencyClass(avgResp)}`}>{formatMs(avgResp)}</span>
        </div>
      )}
      {interrupts != null && (
        <div className="metric-chip">
          <span className="metric-label">Interruptions</span>
          <span className="metric-value">{String(interrupts)}</span>
        </div>
      )}
      {rms != null && (
        <div className="metric-chip">
          <span className="metric-label">Avg Audio</span>
          <span className={`metric-value ${_audioClass(rms)}`}>{rms.toFixed(0)} dB</span>
        </div>
      )}
      {poorTurns != null && poorTurns > 0 && (
        <div className="metric-chip">
          <span className="metric-label">Poor Audio</span>
          <span className="metric-value metric-warn">{String(poorTurns)} turns</span>
        </div>
      )}
    </div>
  );
}

function _latencyClass(ms: number): string {
  if (ms < 1500) return 'metric-good';
  if (ms < 3000) return 'metric-fair';
  return 'metric-warn';
}

function _audioClass(rmsDb: number): string {
  if (rmsDb > -45) return 'metric-good';
  if (rmsDb > -55) return 'metric-fair';
  return 'metric-warn';
}

// ── Main component ─────────────────────────────────────────────────

interface TimelineEventProps {
  event: CallEvent;
  baseTimestamp: number;
}

export function TimelineEvent({ event, baseTimestamp }: TimelineEventProps) {
  const [expanded, setExpanded] = useState(false);
  const color = getEventColor(event);
  const content = renderEventContent(event);

  return (
    <>
      <div className="timeline-event" onClick={() => setExpanded(!expanded)}>
        <div className="timeline-ts">
          {formatRelativeTime(event.timestamp, baseTimestamp)}
        </div>
        <div>
          <span className={`event-badge badge-${color}`}>
            {formatEventLabel(event)}
          </span>
        </div>
        <div className="event-content">
          {content}
        </div>
      </div>
      {expanded && (
        <div className="event-detail">
          <pre>{JSON.stringify(event.data ?? {}, null, 2)}</pre>
        </div>
      )}
    </>
  );
}
