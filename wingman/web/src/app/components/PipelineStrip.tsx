'use client';

import { useEffect, useMemo, useState } from 'react';
import { Activity, ChevronRight, Sparkles, Cpu, Database, Wrench, ShieldCheck, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';

/**
 * Always-visible pipeline strip — every Wingman page renders this at the top so
 * the trader can see the agents/tools that power the surface, with live state
 * pulsing through them while an execution runs.
 *
 * When `executionId` is set the component subscribes to the platform's
 * /api/wingman/executions/{id}/watch SSE stream and lights nodes up as
 * tool_call / tool_result / node_complete / done events arrive. Otherwise
 * it shows the static topology with a quiet ambient pulse.
 */

export interface PipelineNode {
  id: string;            // matches a tool_name or agent slug from the runtime
  label: string;
  kind?: 'agent' | 'tool' | 'sink';
  icon?: 'activity' | 'cpu' | 'db' | 'tool' | 'shield' | 'sparkles';
  hint?: string;         // small tooltip / aside text
}

const ICONS = {
  activity: Activity,
  cpu: Cpu,
  db: Database,
  tool: Wrench,
  shield: ShieldCheck,
  sparkles: Sparkles,
};

type NodeStatus = 'idle' | 'running' | 'done' | 'failed';

export default function PipelineStrip({
  title,
  subtitle,
  nodes,
  executionId,
  onOpenDrawer,
}: {
  title: string;
  subtitle?: string;
  nodes: PipelineNode[];
  executionId?: string | null;
  onOpenDrawer?: () => void;
}) {
  const [status, setStatus] = useState<Record<string, NodeStatus>>({});
  const [meta, setMeta] = useState<{ status?: string; cost?: number; tokens?: number; durationMs?: number; agentName?: string } | null>(null);

  useEffect(() => {
    setStatus({});
    setMeta(null);
    if (!executionId) return;
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
                handleEvent(currentEvent, data);
              } catch { /* ignore malformed */ }
              currentEvent = '';
            }
          }
        }
      } catch { /* user closed or stream ended */ }
    })();

    function handleEvent(t: string, d: any) {
      if (t === 'snapshot') {
        const totalIn = d?.tokens?.in ?? 0;
        const totalOut = d?.tokens?.out ?? 0;
        setMeta({
          status: d?.status,
          cost: d?.cost_so_far,
          tokens: totalIn + totalOut,
          agentName: d?.agent_name,
        });
        if (Array.isArray(d?.nodes)) {
          const next: Record<string, NodeStatus> = {};
          d.nodes.forEach((n: any) => {
            const id = (n.tool_name || n.label || n.id || '').toLowerCase();
            const s = (n.status || '').toLowerCase();
            if (s === 'completed' || s === 'success') next[id] = 'done';
            else if (s === 'running') next[id] = 'running';
            else if (s === 'failed' || s === 'error') next[id] = 'failed';
          });
          setStatus((prev) => ({ ...prev, ...next }));
        }
        return;
      }
      const id = (d?.tool_name || d?.name || '').toLowerCase();
      if (t === 'tool_call') {
        if (id) setStatus((p) => ({ ...p, [id]: 'running' }));
      }
      if (t === 'tool_result' || t === 'node_complete') {
        if (id) setStatus((p) => ({ ...p, [id]: 'done' }));
      }
      if (t === 'error') {
        if (id) setStatus((p) => ({ ...p, [id]: 'failed' }));
      }
      if (t === 'done') {
        setMeta((m) => ({ ...(m || {}), status: 'completed', durationMs: d?.duration_ms, cost: d?.cost, tokens: (d?.input_tokens ?? 0) + (d?.output_tokens ?? 0) }));
      }
    }

    return () => { cancelled = true; ctrl.abort(); };
  }, [executionId]);

  const live = useMemo(() => Object.values(status).some((s) => s === 'running'), [status]);

  return (
    <div className="rounded-2xl border border-emerald-500/15 bg-gradient-to-br from-slate-950/80 via-slate-900/40 to-slate-950/80 p-4 mb-6 relative overflow-hidden">
      {/* ambient gradient ring */}
      <div className="pointer-events-none absolute inset-0 opacity-50">
        <div className="absolute -top-24 -right-24 w-72 h-72 bg-emerald-500/10 blur-3xl rounded-full" />
        <div className="absolute -bottom-24 -left-24 w-72 h-72 bg-cyan-500/5 blur-3xl rounded-full" />
      </div>

      <div className="relative flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-[0.2em] text-emerald-300/70 font-semibold">
              {title}
            </span>
            {executionId && (
              <span className={`inline-flex items-center gap-1.5 text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                live ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200' :
                meta?.status === 'completed' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' :
                meta?.status === 'failed' ? 'border-rose-500/40 bg-rose-500/10 text-rose-200' :
                'border-slate-700 bg-slate-800/40 text-slate-300'
              }`}>
                {live ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Activity className="w-2.5 h-2.5" />}
                {meta?.status || (live ? 'running' : 'subscribed')}
                <span className="opacity-50">#{executionId.slice(0, 6)}</span>
              </span>
            )}
            {!executionId && (
              <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
                <span className="w-1.5 h-1.5 rounded-full bg-slate-600 animate-pulse" />
                pipeline idle — fire any action to see it light up
              </span>
            )}
          </div>
          {subtitle && <p className="text-[11px] text-slate-400 mt-0.5">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2">
          {meta?.cost != null && meta.cost > 0 && (
            <span className="text-[10px] font-mono text-slate-400 px-2 py-0.5 rounded border border-slate-800 bg-slate-900/40">
              ${meta.cost.toFixed(4)}
            </span>
          )}
          {meta?.tokens != null && meta.tokens > 0 && (
            <span className="text-[10px] font-mono text-slate-400 px-2 py-0.5 rounded border border-slate-800 bg-slate-900/40">
              {meta.tokens.toLocaleString()} tok
            </span>
          )}
          {executionId && onOpenDrawer && (
            <button
              onClick={onOpenDrawer}
              className="text-[10px] uppercase tracking-wider font-semibold text-emerald-300 hover:text-emerald-200 inline-flex items-center gap-1"
            >
              full DAG <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      <div className="relative flex items-center gap-1 overflow-x-auto pb-1">
        {nodes.map((n, i) => {
          const Icon = (n.icon ? ICONS[n.icon] : ICONS.tool) || ICONS.tool;
          const s = status[n.id.toLowerCase()] || 'idle';
          const isAgent = n.kind === 'agent';
          const tone =
            s === 'running' ? 'border-cyan-400/60 bg-cyan-500/10 text-cyan-200 ring-2 ring-cyan-400/20 shadow-[0_0_24px_rgba(34,211,238,0.18)]' :
            s === 'done' ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-200' :
            s === 'failed' ? 'border-rose-400/40 bg-rose-500/10 text-rose-200' :
            isAgent ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200' :
            'border-slate-700/70 bg-slate-900/40 text-slate-300';

          return (
            <div key={n.id} className="flex items-center shrink-0">
              <div
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border ${tone} text-[11px] font-medium transition-all duration-300`}
                title={n.hint || n.label}
              >
                <Icon className={`w-3 h-3 ${s === 'running' ? 'animate-pulse' : ''}`} />
                <span className={isAgent ? 'font-semibold tracking-wide' : ''}>{n.label}</span>
                {s === 'running' && <Loader2 className="w-2.5 h-2.5 animate-spin opacity-70" />}
                {s === 'done' && <CheckCircle2 className="w-2.5 h-2.5 opacity-80" />}
                {s === 'failed' && <AlertCircle className="w-2.5 h-2.5 opacity-80" />}
              </div>
              {i < nodes.length - 1 && (
                <ChevronRight className={`w-3 h-3 mx-0.5 shrink-0 ${
                  status[nodes[i + 1].id.toLowerCase()] === 'running' || status[nodes[i + 1].id.toLowerCase()] === 'done'
                    ? 'text-cyan-300' : 'text-slate-600'
                }`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
