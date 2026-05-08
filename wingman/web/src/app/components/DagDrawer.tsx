'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Activity, X, Minimize2, ChevronRight, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';

/**
 * Live DAG drawer — every page renders this once. When `executionId` is set,
 * the drawer subscribes to /api/wingman/executions/{id}/watch (a Server-Sent
 * Events stream that the Wingman API proxies from the platform's
 * /api/executions/{id}/watch). The user can hide / re-show it any time.
 *
 * The platform represents an agent run as a single "agent" node + tool calls
 * underneath; pure ReAct loops don't expand into a structural DAG until the
 * model actually decides which tool to invoke. So in addition to the live
 * stream, callers can pass `expectedTools` — the steps the page knows the
 * agent will call — and the drawer pre-renders them as 'pending' chips that
 * flip to 'running' / 'completed' as tool_call events stream in. Without
 * this, a ReAct agent's drawer stays at "1 node — agent RUNNING" until the
 * very end, which feels broken.
 */
export interface ExpectedTool {
  id: string;          // tool name (e.g. 'eia_open_data')
  label: string;       // visible chip label
  hint?: string;       // small caption
}

export default function DagDrawer({
  executionId,
  onClose,
  expectedTools,
}: {
  executionId: string | null;
  onClose: () => void;
  expectedTools?: ExpectedTool[];
}) {
  const [open, setOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const eventsEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (executionId) setOpen(true);
  }, [executionId]);

  useEffect(() => {
    if (!executionId) return;
    setEvents([]);
    setSnapshot(null);
    // EventSource doesn't pipe non-default 'event:' lines to onmessage. Use
    // a manual fetch+ReadableStream for SSE so we can dispatch by event name.
    let cancelled = false;
    const ctrl = new AbortController();
    (async () => {
      try {
        const res = await fetch(`/api/wingman/executions/${executionId}/watch`, {
          headers: { Accept: 'text/event-stream' },
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let currentEvent = '';
        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim();
            } else if (line.startsWith('data: ') && currentEvent) {
              try {
                const data = JSON.parse(line.slice(6));
                if (currentEvent === 'snapshot') {
                  setSnapshot(data);
                } else {
                  setEvents((prev) => [...prev.slice(-200), { event: currentEvent, data, ts: Date.now() }]);
                }
              } catch { /* ignore malformed line */ }
              currentEvent = '';
            }
          }
        }
      } catch { /* user closed or stream ended */ }
    })();

    // Polling fallback for cases where SSE drops; stops at terminal.
    const refresh = async () => {
      try {
        const r = await fetch(`/api/wingman/executions/${executionId}`);
        if (!r.ok) return;
        const j = await r.json();
        const row = j?.data;
        if (!row || cancelled) return;
        const status = String(row.status || '').toLowerCase();
        const tokensIn = Number(row.input_tokens || 0);
        const tokensOut = Number(row.output_tokens || 0);
        const synthetic: any = {
          execution_id: executionId,
          agent_name: row.agent_name || row.agent_id,
          status,
          progress: row.node_results
            ? { completed: (row.node_results || []).filter((n: any) => n?.status === 'completed').length, total: (row.node_results || []).length || 1 }
            : undefined,
          cost_so_far: row.cost,
          tokens: { in: tokensIn, out: tokensOut },
          nodes: Array.isArray(row.tool_calls) && row.tool_calls.length > 0
            ? [{ id: 'agent', tool_name: 'agent', label: row.agent_name || 'Agent', status, tool_calls: row.tool_calls }]
            : (row.node_results || []),
        };
        setSnapshot((prev: any) => ({ ...(prev || {}), ...synthetic }));
        if (status === 'completed' || status === 'failed' || status === 'error' || status === 'cancelled') {
          clearInterval(t);
        }
      } catch { /* keep polling */ }
    };
    refresh();
    const t = setInterval(refresh, 3000);

    return () => {
      cancelled = true;
      ctrl.abort();
      clearInterval(t);
    };
  }, [executionId]);

  useEffect(() => {
    eventsEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length]);

  if (!executionId) return null;

  return (
    <>
      {/* Floating chip when collapsed */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          data-testid="dag-drawer-open"
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 bg-slate-900 border border-emerald-500/30 text-emerald-300 px-3 py-2 rounded-full shadow-lg hover:bg-slate-800 transition-colors text-xs font-medium"
        >
          <Activity className="w-3.5 h-3.5 animate-pulse" />
          live agent
          <ChevronRight className="w-3 h-3" />
        </button>
      )}

      {/* Side drawer */}
      {open && (
        <div className="fixed top-0 right-0 bottom-0 w-[420px] z-40 bg-slate-900/95 backdrop-blur-xl border-l border-slate-800 shadow-2xl flex flex-col"
             data-testid="dag-drawer">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              <div>
                <div className="text-xs text-slate-400">Live execution</div>
                <div className="text-[10px] font-mono text-slate-500">#{executionId.slice(0, 8)}</div>
              </div>
            </div>
            <div className="flex gap-1">
              <button onClick={() => setOpen(false)} title="Hide" className="p-1.5 text-slate-400 hover:text-white">
                <Minimize2 className="w-3.5 h-3.5" />
              </button>
              <button onClick={onClose} title="Close" className="p-1.5 text-slate-400 hover:text-white">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Snapshot summary */}
          {snapshot && (
            <div className="px-4 py-3 border-b border-slate-800 text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-slate-500">status</span>
                <span className={`font-medium ${
                  snapshot.status === 'completed' ? 'text-emerald-300' :
                  snapshot.status === 'failed' ? 'text-rose-300' :
                  snapshot.status === 'running' ? 'text-cyan-300' :
                  'text-slate-300'
                }`}>{snapshot.status}</span>
              </div>
              {snapshot.agent_name && (
                <div className="flex justify-between"><span className="text-slate-500">agent</span><span className="text-slate-300">{snapshot.agent_name}</span></div>
              )}
              {snapshot.progress && (
                <div className="flex justify-between"><span className="text-slate-500">progress</span>
                  <span className="text-slate-300">{snapshot.progress.completed}/{snapshot.progress.total}</span></div>
              )}
              {snapshot.cost_so_far != null && (
                <div className="flex justify-between"><span className="text-slate-500">cost so far</span>
                  <span className="text-slate-300">${(snapshot.cost_so_far || 0).toFixed(4)}</span></div>
              )}
              {snapshot.tokens && (
                <div className="flex justify-between"><span className="text-slate-500">tokens</span>
                  <span className="text-slate-300">{snapshot.tokens.in?.toLocaleString?.() || 0} → {snapshot.tokens.out?.toLocaleString?.() || 0}</span></div>
              )}
            </div>
          )}

          {/* DAG nodes — merge the structural snapshot from the runtime
              with the caller-supplied `expectedTools` list. Pure ReAct
              agents (mode='agent') only emit one umbrella "agent" node
              and accumulate `tool_calls` underneath it; without merging
              we'd render a single chip + "waiting for events..." until
              the very end, which feels broken. With the merge: every
              expected step is visible from t=0 and lights up as
              `tool_call` events stream in. */}
          {(() => {
            const snapNodes: any[] = Array.isArray(snapshot?.nodes) ? snapshot.nodes : [];
            const calls: any[] = snapNodes.flatMap((n) => Array.isArray(n.tool_calls) ? n.tool_calls : []);
            const callStatus = new Map<string, string>();
            for (const c of calls) {
              const tn = c.tool_name || c.name;
              if (!tn) continue;
              const ok = c.status || (c.completed_at ? 'completed' : c.error ? 'failed' : 'running');
              callStatus.set(tn, ok);
            }
            // Live event stream: tool_call (start) → tool_result (end)
            for (const e of events) {
              const tn = e.data?.tool_name || e.data?.name;
              if (!tn) continue;
              if (e.event === 'tool_call') callStatus.set(tn, callStatus.get(tn) === 'completed' ? 'completed' : 'running');
              if (e.event === 'tool_result') callStatus.set(tn, e.data?.error ? 'failed' : 'completed');
            }
            // Compose: agent envelope first (from snapshot), then expected tools.
            type Row = { id: string; label: string; status: string; sub?: string };
            const rows: Row[] = [];
            const agentNode = snapNodes.find((n) => n.tool_name === 'agent' || n.id === 'agent');
            if (agentNode) {
              rows.push({
                id: 'agent',
                label: agentNode.label || snapshot?.agent_name || 'Agent',
                status: (agentNode.status || '').toLowerCase() || 'pending',
                sub: 'orchestrator',
              });
            }
            const seenInExpected = new Set<string>();
            if (Array.isArray(expectedTools)) {
              for (const t of expectedTools) {
                if (t.id === 'agent' || /^wingman-/.test(t.id)) continue;  // skip the agent slug, only chain tool steps
                seenInExpected.add(t.id);
                rows.push({
                  id: t.id,
                  label: t.label,
                  status: callStatus.get(t.id) || 'pending',
                  sub: t.hint,
                });
              }
            }
            // Catch any tool the agent invoked that wasn't in the expected list
            for (const [tn, s] of callStatus.entries()) {
              if (seenInExpected.has(tn)) continue;
              rows.push({ id: tn, label: tn, status: s });
            }
            if (rows.length === 0) return null;
            const dotFor = (s: string) =>
              s === 'completed' || s === 'success' ? '●' :
              s === 'failed' || s === 'error' ? '✕' :
              s === 'running' ? '◐' :
              '○';
            return (
              <div className="px-3 py-3 border-b border-slate-800">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
                  DAG nodes ({rows.length})
                </div>
                <div className="space-y-1">
                  {rows.map((r, i) => {
                    const s = r.status;
                    const tone =
                      s === 'completed' || s === 'success' ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200' :
                      s === 'failed' || s === 'error' ? 'border-rose-500/30 bg-rose-500/5 text-rose-200' :
                      s === 'running' ? 'border-cyan-500/30 bg-cyan-500/5 text-cyan-200 animate-pulse' :
                      'border-slate-700/40 bg-slate-800/30 text-slate-400';
                    return (
                      <div key={`${r.id}-${i}`} className={`text-[11px] rounded border px-2 py-1.5 ${tone}`}>
                        <div className="flex items-center justify-between gap-2">
                          <span className="flex items-center gap-2 min-w-0">
                            <span className="opacity-60">{dotFor(s)}</span>
                            <span className="font-mono truncate">{r.label}</span>
                          </span>
                          <span className="text-[9px] uppercase tracking-wider opacity-70 shrink-0">{s}</span>
                        </div>
                        {r.sub && <div className="text-[9px] opacity-50 mt-0.5 ml-4 truncate">{r.sub}</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}

          {/* Event tail — populated while the execution streams.
              Empty after-the-fact for completed runs; the DAG nodes
              above carry the structural picture. */}
          <div className="flex-1 overflow-y-auto px-2 py-2 font-mono text-[11px] space-y-1">
            {events.length === 0 && snapshot?.status !== 'completed' && snapshot?.status !== 'failed' && (
              <div className="px-2 py-4 text-slate-500 flex items-center gap-2">
                <Loader2 className="w-3 h-3 animate-spin" /> waiting for events...
              </div>
            )}
            {events.length === 0 && (snapshot?.status === 'completed' || snapshot?.status === 'failed') && (
              <div className="px-2 py-3 text-[10px] text-slate-500 italic">
                Execution finished before this drawer subscribed — DAG nodes above show the structural snapshot. Re-run for live event streaming.
              </div>
            )}
            {events.map((e, i) => (
              <EventRow key={i} ev={e} />
            ))}
            <div ref={eventsEnd} />
          </div>
        </div>
      )}
    </>
  );
}

function EventRow({ ev }: { ev: any }) {
  const t = ev.event;
  const d = ev.data || {};
  let color = 'text-slate-400';
  let Icon = Activity;
  if (t === 'tool_call') { color = 'text-cyan-300'; }
  if (t === 'tool_result') { color = 'text-slate-500'; }
  if (t === 'node_complete' || t === 'done') { color = 'text-emerald-300'; Icon = CheckCircle2; }
  if (t === 'error') { color = 'text-rose-300'; Icon = AlertCircle; }
  return (
    <div className="px-2 py-1 rounded hover:bg-slate-800/40">
      <div className={`flex items-center gap-1.5 ${color}`}>
        <Icon className="w-3 h-3 shrink-0" />
        <span className="font-semibold uppercase tracking-wider text-[10px]">{t}</span>
        {d.name && <span className="text-slate-300">· {d.name}</span>}
        {d.tool_name && <span className="text-slate-300">· {d.tool_name}</span>}
        {d.status && <span className="text-slate-500">· {d.status}</span>}
      </div>
      {(d.text || d.message || d.result) && (
        <div className="text-slate-500 ml-4 truncate" title={String(d.text ?? d.message ?? d.result ?? '')}>
          {String(d.text ?? d.message ?? d.result ?? '').slice(0, 120)}
        </div>
      )}
    </div>
  );
}
