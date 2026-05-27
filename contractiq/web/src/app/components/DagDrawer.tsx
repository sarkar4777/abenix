'use client';

import { useEffect, useRef, useState } from 'react';
import { Activity, X, Minimize2, ChevronRight, CheckCircle2, Loader2, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import DeskNetworkCanvas from './DeskNetworkCanvas';
import DeskNarrationFeed from './DeskNarrationFeed';
import { useNarrationStream } from './useNarrationStream';

/**
 * Live DAG drawer — every page renders this once. When `executionId` is set,
 * the drawer subscribes to /api/contractiq-watch/{id}, a Server-Sent Events
 * stream the contractiq-api forwards from Abenix's /api/executions/{id}/watch.
 * All logs + traces live in Abenix; this component is a read-only viewer.
 *
 * For ReAct-style agents that don't declare a static DAG up front, callers
 * pass `expectedTools` so the drawer pre-renders pending chips that flip to
 * running / completed as tool_call events stream in.
 */
export interface ExpectedTool {
  id: string;
  label: string;
  hint?: string;
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
  const terminalRef = useRef<boolean>(false);
  const [dagOpen, setDagOpen] = useState(true);
  const [netOpen, setNetOpen] = useState(true);
  const [feedOpen, setFeedOpen] = useState(true);
  const { events: narrationEvents } = useNarrationStream(executionId);

  const TERMINAL_STATUS = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);
  const mergeSnapshot = (incoming: any) => {
    setSnapshot((prev: any) => {
      const next: any = { ...(prev || {}), ...(incoming || {}) };
      if (terminalRef.current && prev?.status) {
        next.status = prev.status;
      }
      const s = String(next.status || '').toLowerCase();
      if (TERMINAL_STATUS.has(s)) terminalRef.current = true;
      return next;
    });
  };

  useEffect(() => {
    if (executionId) setOpen(true);
  }, [executionId]);

  useEffect(() => {
    if (!executionId) return;
    setEvents([]);
    setSnapshot(null);
    terminalRef.current = false;
    let cancelled = false;
    const ctrl = new AbortController();
    (async () => {
      try {
        const res = await fetch(`/api/contractiq-watch/${executionId}`, {
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
                  mergeSnapshot(data);
                } else {
                  setEvents((prev) => [...prev.slice(-200), { event: currentEvent, data, ts: Date.now() }]);
                  if (currentEvent === 'done' || currentEvent === 'node_complete' || currentEvent === 'error') {
                    const s = String(data?.status || '').toLowerCase();
                    if (TERMINAL_STATUS.has(s) || currentEvent === 'done' || currentEvent === 'error') {
                      terminalRef.current = true;
                      mergeSnapshot({ status: data?.status || (currentEvent === 'error' ? 'failed' : 'completed') });
                    }
                  }
                }
              } catch { /* ignore malformed line */ }
              currentEvent = '';
            }
          }
        }
      } catch { /* user closed or stream ended */ }
    })();

    const refresh = async () => {
      try {
        const r = await fetch(`/api/contractiq-executions/${executionId}`);
        if (!r.ok) return;
        const j = await r.json();
        const row = j?.data;
        if (!row || cancelled) return;
        const status = String(row.status || '').toLowerCase();
        const tokensIn = Number(row.input_tokens || 0);
        const tokensOut = Number(row.output_tokens || 0);
        const rowToolCalls = Array.isArray(row.tool_calls) ? row.tool_calls : [];
        const rowNodeResults = Array.isArray(row.node_results) ? row.node_results : [];
        const synthetic: any = {
          execution_id: executionId,
          agent_name: row.agent_name || row.agent_id,
          status,
          progress: row.node_results
            ? { completed: rowNodeResults.filter((n: any) => n?.status === 'completed').length, total: rowNodeResults.length || 1 }
            : undefined,
          cost_so_far: row.cost,
          tokens: { in: tokensIn, out: tokensOut },
        };
        if (rowToolCalls.length > 0) {
          synthetic.nodes = [{ id: 'agent', tool_name: 'agent', label: row.agent_name || 'Agent', status, tool_calls: rowToolCalls }];
        } else if (rowNodeResults.length > 0) {
          synthetic.nodes = rowNodeResults;
        }
        mergeSnapshot(synthetic);
        if (status === 'completed' || status === 'failed' || status === 'error' || status === 'cancelled') {
          terminalRef.current = true;
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

      {open && (
        <div className="fixed top-0 right-0 bottom-0 w-[480px] z-40 bg-slate-900/95 backdrop-blur-xl border-l border-slate-800 shadow-2xl flex flex-col"
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

          <div className="flex-1 overflow-y-auto flex flex-col">
            <SectionHeader label="DAG" open={dagOpen} onToggle={() => setDagOpen((v) => !v)} />
            {dagOpen && (
              <div className="border-b border-slate-800/60">
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
                  for (const e of events) {
                    const tn = e.data?.tool_name || e.data?.name;
                    if (!tn) continue;
                    if (e.event === 'tool_call') callStatus.set(tn, callStatus.get(tn) === 'completed' ? 'completed' : 'running');
                    if (e.event === 'tool_result') callStatus.set(tn, e.data?.error ? 'failed' : 'completed');
                  }
                  type Row = { id: string; label: string; status: string; sub?: string };
                  const rows: Row[] = [];
                  const agentNode = snapNodes.find((n) => n.tool_name === 'agent' || n.id === 'agent');
                  const overallStatus = String(snapshot?.status || '').toLowerCase();
                  const isTerminal = TERMINAL_STATUS.has(overallStatus);
                  const sweep = (s: string): string => {
                    if (!isTerminal) return s;
                    if (s === 'running' || s === 'pending') {
                      if (overallStatus === 'completed' || overallStatus === 'succeeded') return 'completed';
                      return overallStatus;
                    }
                    return s;
                  };
                  if (agentNode) {
                    const nodeStatus = (agentNode.status || '').toLowerCase() || 'pending';
                    rows.push({
                      id: 'agent',
                      label: agentNode.label || snapshot?.agent_name || 'Agent',
                      status: isTerminal ? overallStatus : nodeStatus,
                      sub: 'orchestrator',
                    });
                  }
                  const seenInExpected = new Set<string>();
                  if (Array.isArray(expectedTools)) {
                    for (const t of expectedTools) {
                      if (t.id === 'agent' || /^ciq-/.test(t.id)) continue;
                      seenInExpected.add(t.id);
                      const raw = callStatus.get(t.id) || 'pending';
                      rows.push({ id: t.id, label: t.label, status: sweep(raw), sub: t.hint });
                    }
                  }
                  for (const [tn, s] of callStatus.entries()) {
                    if (seenInExpected.has(tn)) continue;
                    rows.push({ id: tn, label: tn, status: sweep(s) });
                  }
                  if (rows.length === 0) {
                    return <div className="px-3 py-3 text-[10px] text-slate-500 italic">no nodes yet</div>;
                  }
                  const dotFor = (s: string) =>
                    s === 'completed' || s === 'success' ? '●' :
                    s === 'failed' || s === 'error' ? '✕' :
                    s === 'running' ? '◐' :
                    '○';
                  return (
                    <div className="px-3 py-2 max-h-[180px] overflow-y-auto">
                      <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1.5">
                        {rows.length} node{rows.length === 1 ? '' : 's'}
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

                <div className="px-2 py-1 max-h-[140px] overflow-y-auto font-mono text-[10px] space-y-0.5 border-t border-slate-800/60">
                  {events.length === 0 && snapshot?.status !== 'completed' && snapshot?.status !== 'failed' && (
                    <div className="px-2 py-3 text-slate-500 flex items-center gap-2">
                      <Loader2 className="w-3 h-3 animate-spin" /> waiting for events...
                    </div>
                  )}
                  {events.length === 0 && (snapshot?.status === 'completed' || snapshot?.status === 'failed') && (
                    <div className="px-2 py-2 text-[9px] text-slate-500 italic">
                      execution finished before this drawer subscribed — DAG nodes carry the snapshot.
                    </div>
                  )}
                  {events.map((e, i) => (<EventRow key={i} ev={e} />))}
                  <div ref={eventsEnd} />
                </div>
              </div>
            )}

            <SectionHeader label="Network · live" open={netOpen} onToggle={() => setNetOpen((v) => !v)} count={narrationEvents.length} />
            {netOpen && executionId && (
              <div className="border-b border-slate-800/60 p-2">
                <DeskNetworkCanvas rootExecutionId={executionId} events={narrationEvents} height={240} title="Live agent network" />
              </div>
            )}

            <SectionHeader label="Narration · live" open={feedOpen} onToggle={() => setFeedOpen((v) => !v)} count={narrationEvents.length} />
            {feedOpen && executionId && (
              <div className="p-2">
                <DeskNarrationFeed rootExecutionId={executionId} events={narrationEvents} height={240} />
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function SectionHeader({ label, open, onToggle, count }: { label: string; open: boolean; onToggle: () => void; count?: number }) {
  const Chev = open ? ChevronUp : ChevronDown;
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center justify-between px-3 py-2 border-b border-slate-800/40 bg-slate-900/40 hover:bg-slate-800/40 text-left"
    >
      <span className="text-[10px] uppercase tracking-[0.18em] text-slate-300 font-semibold flex items-center gap-2">
        {label}
        {count != null && (
          <span className="text-[9px] text-slate-500 font-mono normal-case tracking-normal">{count}</span>
        )}
      </span>
      <Chev className="w-3.5 h-3.5 text-slate-400" />
    </button>
  );
}

function EventRow({ ev }: { ev: any }) {
  const t = ev.event;
  const d = ev.data || {};
  let color = 'text-slate-400';
  let Icon: any = Activity;
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
