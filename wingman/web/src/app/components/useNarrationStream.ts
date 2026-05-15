'use client';

import { useEffect, useState, useRef } from 'react';

export interface NarrationEvent {
  ts: number;
  execution_id?: string;
  root_execution_id?: string;
  phase: 'tool_call' | 'tool_result' | 'sub_started' | 'sub_finished' | 'sub_timeout' | 'narration' | 'heartbeat' | 'done';
  tool?: string;
  agent_id?: string;
  agent_name?: string;
  agent_slug?: string;
  sub_execution_id?: string;
  arguments_preview?: string;
  result_preview?: string;
  is_error?: boolean;
  duration_ms?: number;
  cost_usd?: number;
  status?: string;
  message?: string;
  tone?: 'info' | 'step' | 'finding' | 'alert' | 'done';
}

export function useNarrationStream(executionId: string | null, opts?: { replay?: boolean; speed?: number }) {
  const [events, setEvents] = useState<NarrationEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const reset = () => setEvents([]);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!executionId) return;
    setEvents([]);
    setConnected(false);
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    (async () => {
      try {
        const qs = opts?.replay
          ? `?replay=1${opts.speed ? `&speed=${opts.speed}` : ''}`
          : '';
        const res = await fetch(`/api/wingman-narration/${executionId}${qs}`, {
          headers: { Accept: 'text/event-stream' },
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) return;
        setConnected(true);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let currentEvent = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split('\n');
          buf = lines.pop() || '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                if (currentEvent === 'progress' || currentEvent === 'start') {
                  setEvents((prev) => [...prev, { ...data, _kind: currentEvent } as any]);
                }
              } catch {}
              currentEvent = '';
            }
          }
        }
      } catch {}
      setConnected(false);
    })();

    return () => {
      ctrl.abort();
      setConnected(false);
    };
  }, [executionId, opts?.replay, opts?.speed]);

  return { events, connected, reset };
}
