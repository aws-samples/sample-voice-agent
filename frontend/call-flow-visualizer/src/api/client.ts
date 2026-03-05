import type { CallListResponse, CallTimeline, CallSummary, SearchResponse } from '../types';

const API_BASE = '/api';

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export async function listCalls(params?: {
  date_from?: string;
  days_back?: number;
  disposition?: string;
  limit?: number;
  next_token?: string;
}): Promise<CallListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.date_from) searchParams.set('date_from', params.date_from);
  if (params?.days_back) searchParams.set('days_back', String(params.days_back));
  if (params?.disposition) searchParams.set('disposition', params.disposition);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  if (params?.next_token) searchParams.set('next_token', params.next_token);
  const qs = searchParams.toString();
  return fetchJson<CallListResponse>(`${API_BASE}/calls${qs ? `?${qs}` : ''}`);
}

export async function getCallTimeline(callId: string): Promise<CallTimeline> {
  return fetchJson<CallTimeline>(`${API_BASE}/calls/${encodeURIComponent(callId)}`);
}

export async function getCallSummary(callId: string): Promise<CallSummary> {
  return fetchJson<CallSummary>(`${API_BASE}/calls/${encodeURIComponent(callId)}/summary`);
}

export async function searchCalls(params: {
  tool_name?: string;
  call_id?: string;
  date?: string;
}): Promise<SearchResponse> {
  const searchParams = new URLSearchParams();
  if (params.tool_name) searchParams.set('tool_name', params.tool_name);
  if (params.call_id) searchParams.set('call_id', params.call_id);
  if (params.date) searchParams.set('date', params.date);
  return fetchJson<SearchResponse>(`${API_BASE}/search?${searchParams.toString()}`);
}
