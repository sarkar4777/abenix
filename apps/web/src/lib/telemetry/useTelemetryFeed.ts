'use client';

import { useEffect, useRef, useState } from 'react';
import { API_URL, apiFetch } from '@/lib/api-client';
import { createCoalescer, normalizeEvent, openStream, type StreamState } from './stream';
import { useTelemetry } from './store';
import type { DeviceRow, NodeDetail } from './types';

export type FeedScope =
  | { kind: 'nodes'; nodes: string[] }
  | { kind: 'device'; group: string; node: string; device: string };

export function streamUrl(scope: FeedScope): string {
  const p = new URLSearchParams();
  if (scope.kind === 'device') {
    p.set('group', scope.group);
    p.set('node', scope.node);
    if (scope.device) p.set('device', scope.device);
  } else if (scope.nodes.length) {
    p.set('nodes', scope.nodes.join(','));
  }
  const qs = p.toString();
  return `${API_URL}/api/telemetry/stream${qs ? `?${qs}` : ''}`;
}

const scopeKey = (s: FeedScope) => (s.kind === 'device' ? `d:${s.group}/${s.node}/${s.device}` : `n:${[...s.nodes].sort().join(',')}`);

export interface FeedStatus {
  state: StreamState | 'idle';
  retryInMs?: number;
  // the stream is not available, values come from polling instead
  polling: boolean;
}

// live updates for what is on screen, painted at most 10 times a second
export function useTelemetryFeed(scope: FeedScope | null, enabled = true): FeedStatus {
  const [status, setStatus] = useState<FeedStatus>({ state: 'idle', polling: false });
  const coalescer = useRef(createCoalescer((b) => useTelemetry.getState().applyBatch(b), 100));
  const key = scope ? scopeKey(scope) : '';
  const scopeRef = useRef(scope);
  scopeRef.current = scope;

  useEffect(() => {
    const c = coalescer.current;
    return () => c.stop();
  }, []);

  useEffect(() => {
    if (!enabled || !scopeRef.current) return;
    if (scopeRef.current.kind === 'nodes' && scopeRef.current.nodes.length === 0) return;
    let close: (() => void) | null = null;
    // a short wait so scrolling past rows does not open and close streams
    const t = setTimeout(() => {
      const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
      close = openStream({
        url: streamUrl(scopeRef.current!),
        token,
        onMessage: (m) => {
          for (const e of normalizeEvent(m)) coalescer.current.push(e);
        },
        onState: (s, d) => {
          if (s === 'closed') return;
          setStatus({ state: s, retryInMs: d?.retryInMs, polling: s === 'unsupported' || s === 'denied' || s === 'retrying' });
        },
      });
    }, 400);
    return () => {
      clearTimeout(t);
      close?.();
    };
  }, [key, enabled]);

  // when the stream is down, poll so the numbers still move
  useEffect(() => {
    if (!enabled || !status.polling || !scopeRef.current) return;
    let stop = false;
    const tick = async () => {
      const s = scopeRef.current;
      if (!s || stop) return;
      if (s.kind === 'device') {
        const res = await apiFetch<NodeDetail>(`/api/telemetry/devices/${encodeURIComponent(s.group)}/${encodeURIComponent(s.node)}${s.device ? `?device=${encodeURIComponent(s.device)}` : ''}`, { silent: true });
        if (stop || !res.data) return;
        pushDetail(res.data, s.device, (e) => coalescer.current.push(e));
      } else {
        const res = await apiFetch<DeviceRow[]>('/api/telemetry/devices?limit=5000', { silent: true });
        if (stop || !Array.isArray(res.data)) return;
        coalescer.current.push({ kind: 'snapshot', rows: res.data });
      }
    };
    void tick();
    const h = setInterval(tick, scopeRef.current.kind === 'device' ? 1000 : 3000);
    return () => {
      stop = true;
      clearInterval(h);
    };
  }, [status.polling, key, enabled]);

  return status;
}

// a node detail response as stream events, so polling and streaming share one path
export function pushDetail(d: NodeDetail, device: string, push: (e: Parameters<ReturnType<typeof createCoalescer>['push']>[0]) => void) {
  const group = d.group;
  const node = d.node;
  if (d.metrics?.length) push({ kind: 'metrics', group, node, device: '', metrics: d.metrics });
  for (const dev of d.devices || []) {
    const { metrics, ...row } = dev;
    push({ kind: 'device', row: { ...row, group, node, device: dev.device ?? '' } });
    if (metrics?.length && (!device || dev.device === device)) push({ kind: 'metrics', group, node, device: dev.device ?? '', metrics });
  }
}
