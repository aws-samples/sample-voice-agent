/** A single event in the call timeline (stored in DynamoDB). */
export interface CallEvent {
  PK: string;
  SK: string;
  call_id: string;
  session_id: string;
  event_type: string;
  timestamp: string;
  turn_number?: number;
  data?: Record<string, unknown>;
}

/** Enriched call item returned by GET /api/calls (deduplicated). */
export interface CallListItem {
  call_id: string;
  session_id: string;
  timestamp: string;
  status?: string;
  duration_seconds?: number;
  turn_count?: number;
  avg_response_ms?: number;
  avg_rms_db?: number;
  poor_audio_turns?: number;
  interruption_count?: number;
}

/** Full call timeline returned by GET /api/calls/{id}. */
export interface CallTimeline {
  call_id: string;
  session_id: string;
  started_at?: string;
  ended_at?: string;
  end_status?: string;
  turn_count?: number;
  duration_seconds?: number;
  event_count: number;
  events: CallEvent[];
  metrics?: Record<string, unknown>;
}

export interface CallSummary {
  call_id: string;
  session_id: string;
  started_at?: string;
  ended_at?: string;
  end_status?: string;
  turn_count?: number;
  event_count: number;
  metrics?: Record<string, unknown>;
}

export interface CallListResponse {
  calls: CallListItem[];
  count: number;
  next_token?: string;
}

export interface SearchResponse {
  results: CallEvent[];
  count: number;
}

// ── Sort types ────────────────────────────────────────────────────

export type SortColumn =
  | 'timestamp'
  | 'duration_seconds'
  | 'turn_count'
  | 'avg_response_ms'
  | 'avg_rms_db'
  | 'status';

export type SortDirection = 'asc' | 'desc';

export interface SortState {
  column: SortColumn;
  direction: SortDirection;
}

// ── Badge colors ──────────────────────────────────────────────────

export type EventBadgeColor =
  | 'gray'
  | 'blue'
  | 'green'
  | 'lightgray'
  | 'orange'
  | 'purple'
  | 'red'
  | 'darkgray'
  | 'yellow'
  | 'teal';

export function getEventColor(event: CallEvent): EventBadgeColor {
  switch (event.event_type) {
    case 'session_started':
      return 'gray';
    case 'session_ended':
      return 'gray';
    case 'conversation_turn':
      return event.data?.speaker === 'user' ? 'blue' : 'green';
    case 'turn_completed':
      return 'lightgray';
    case 'tool_execution':
      return 'orange';
    case 'barge_in':
      return 'red';
    case 'call_metrics_summary':
      return 'darkgray';
    case 'poor_audio_detected':
      return 'yellow';
    case 'audio_clipping_detected':
      return 'red';
    case 'agent_transition':
      return 'teal';
    default:
      if (event.event_type === 'a2a_tool_call_start') return 'purple';
      if (event.event_type === 'a2a_tool_call_success') return 'purple';
      if (event.event_type === 'a2a_tool_call_cache_hit') return 'purple';
      if (event.event_type === 'a2a_tool_call_timeout') return 'red';
      if (event.event_type === 'a2a_tool_call_error') return 'red';
      if (event.event_type.startsWith('flow_a2a_call_')) {
        return event.event_type.includes('error') || event.event_type.includes('timeout')
          ? 'red'
          : 'purple';
      }
      return 'gray';
  }
}

// ── Formatting helpers ────────────────────────────────────────────

/** "2026-03-04T16:56:23.833598Z" → "4:56:23 PM" */
export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    });
  } catch {
    return iso;
  }
}

/** "2026-03-04T16:56:23.833598Z" → "Mar 4, 2026 4:56 PM" */
export function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return iso;
  }
}

/** 50.65 → "51s" or 125.3 → "2m 5s" */
export function formatDuration(seconds?: number): string {
  if (seconds == null) return '-';
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

/** 2167.6 → "2.2s" */
export function formatMs(ms?: number): string {
  if (ms == null) return '-';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** -63.5 → "Good" / "Fair" / "Poor" with thresholds */
export function audioQualityLabel(rmsDb?: number): { label: string; level: 'good' | 'fair' | 'poor' } {
  if (rmsDb == null) return { label: '-', level: 'good' };
  if (rmsDb > -45) return { label: 'Good', level: 'good' };
  if (rmsDb > -55) return { label: 'Fair', level: 'fair' };
  return { label: 'Poor', level: 'poor' };
}
