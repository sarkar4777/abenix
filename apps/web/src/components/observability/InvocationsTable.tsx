'use client';

import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, XCircle, ChevronDown, ChevronRight, RefreshCw, Activity } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

export interface InvocationStats {
  window: string;
  total: number;
  errors: number;
  success_rate: number | null;
  avg_duration_ms: number | null;
  total_cost_usd?: number;
  top_agents: { agent_id: string; count: number }[];
}

export interface InvocationRow {
  id: string;
  execution_id?: string | null;
  agent_id?: string | null;
  duration_ms?: number | null;
  is_error: boolean;
  error_message?: string | null;
  input_payload?: any;
  output?: any;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  operation?: string;
  predicted_class?: string | null;
  confidence?: number | null;
  cost_usd?: number | null;
  created_at: string;
}

interface Props {
  kind: 'code_asset' | 'ml_model';
  resourceId: string;
}

function fmtAgo(iso: string): string {
  try {
    const t = new Date(iso).getTime();
    const s = Math.floor((Date.now() - t) / 1000);
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  } catch {
    return iso;
  }
}

export default function InvocationsTable({ kind, resourceId }: Props) {
  const [rows, setRows] = useState<InvocationRow[]>([]);
  const [stats, setStats] = useState<InvocationStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const basePath = kind === 'code_asset' ? '/api/code-assets' : '/api/ml-models';

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiFetch<{ items: InvocationRow[]; total: number }>(`${basePath}/${resourceId}/invocations?limit=50`);
      setRows(r.data?.items || []);
      const s = await apiFetch<InvocationStats>(`${basePath}/${resourceId}/stats?window=24h`);
      setStats(s.data || null);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, [basePath, resourceId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-700 bg-slate-900/30 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-white flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-cyan-400" /> 24h stats
          </h3>
          <button onClick={load} className="text-[10px] text-slate-400 hover:text-cyan-300 flex items-center gap-1">
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> refresh
          </button>
        </div>
        {stats ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
            <Stat label="Total" value={stats.total.toString()} />
            <Stat label="Errors" value={`${stats.errors}`} tone={stats.errors > 0 ? 'rose' : 'emerald'} />
            <Stat label="Success rate" value={stats.success_rate != null ? `${(stats.success_rate * 100).toFixed(1)}%` : '—'} />
            <Stat label="Avg duration" value={stats.avg_duration_ms != null ? `${stats.avg_duration_ms} ms` : '—'} />
            {stats.total_cost_usd != null && (
              <Stat label="24h cost" value={`$${stats.total_cost_usd.toFixed(4)}`} />
            )}
            {stats.top_agents.length > 0 && (
              <div className="col-span-2 md:col-span-3">
                <div className="text-[9px] uppercase tracking-wider text-slate-500 mb-1">Top agents</div>
                <div className="flex flex-wrap gap-1.5">
                  {stats.top_agents.map((a) => (
                    <span key={a.agent_id} className="text-[10px] font-mono text-slate-300 bg-slate-800 px-2 py-0.5 rounded">
                      {a.agent_id.slice(0, 8)} · {a.count}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-[11px] text-slate-500 italic">no stats yet</p>
        )}
      </div>

      <div className="rounded-xl border border-slate-700 bg-slate-900/30 overflow-hidden">
        <div className="px-4 py-2 border-b border-slate-700/60 flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Recent invocations</span>
          <span className="text-[10px] text-slate-500">{rows.length} shown</span>
        </div>
        {loading && rows.length === 0 && <div className="px-4 py-6 text-[11px] text-slate-500 italic">loading…</div>}
        {!loading && rows.length === 0 && (
          <div className="px-4 py-8 text-center text-[11px] text-slate-500">
            No invocations yet. Fire any agent that uses this resource — they'll appear here.
          </div>
        )}
        <div className="divide-y divide-slate-800/40">
          {rows.map((r) => {
            const open = expandedId === r.id;
            return (
              <div key={r.id} className="px-4 py-2 text-[11px] hover:bg-slate-900/40">
                <button
                  className="w-full flex items-center gap-3 text-left"
                  onClick={() => setExpandedId(open ? null : r.id)}
                >
                  {open ? <ChevronDown className="w-3 h-3 text-slate-500" /> : <ChevronRight className="w-3 h-3 text-slate-500" />}
                  {r.is_error ? (
                    <XCircle className="w-3.5 h-3.5 text-rose-400" />
                  ) : (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  )}
                  <span className="text-slate-500 font-mono text-[10px]">{fmtAgo(r.created_at)}</span>
                  {r.agent_id && (
                    <span className="text-slate-400 font-mono text-[10px]">agent {r.agent_id.slice(0, 8)}</span>
                  )}
                  {r.operation && (
                    <span className="text-cyan-300 text-[10px]">{r.operation}</span>
                  )}
                  {r.predicted_class && (
                    <span className="text-emerald-300 text-[10px]">→ {r.predicted_class}</span>
                  )}
                  {r.confidence != null && (
                    <span className="text-slate-400 text-[10px]">conf {(r.confidence * 100).toFixed(1)}%</span>
                  )}
                  <span className="ml-auto text-slate-400">{r.duration_ms != null ? `${r.duration_ms} ms` : '—'}</span>
                  {r.cost_usd != null && r.cost_usd > 0 && (
                    <span className="text-emerald-400 font-mono">${r.cost_usd.toFixed(4)}</span>
                  )}
                  {r.exit_code != null && (
                    <span className={`font-mono ${r.exit_code === 0 ? 'text-slate-500' : 'text-rose-400'}`}>exit {r.exit_code}</span>
                  )}
                </button>
                {open && (
                  <div className="mt-2 ml-7 space-y-2 text-[10px] font-mono">
                    {r.execution_id && (
                      <div>
                        <span className="text-slate-500">execution</span>{' '}
                        <a href={`/executions/${r.execution_id}`} className="text-cyan-400 hover:underline">
                          {r.execution_id}
                        </a>
                      </div>
                    )}
                    {r.error_message && (
                      <div>
                        <div className="text-rose-400">error</div>
                        <pre className="bg-rose-500/5 border border-rose-500/20 rounded p-2 text-rose-200 max-h-32 overflow-auto whitespace-pre-wrap">{r.error_message}</pre>
                      </div>
                    )}
                    {r.input_payload != null && (
                      <div>
                        <div className="text-slate-500">input</div>
                        <pre className="bg-slate-950/60 border border-slate-700/40 rounded p-2 text-slate-300 max-h-32 overflow-auto">{JSON.stringify(r.input_payload, null, 2)}</pre>
                      </div>
                    )}
                    {r.output != null && (
                      <div>
                        <div className="text-slate-500">output</div>
                        <pre className="bg-slate-950/60 border border-slate-700/40 rounded p-2 text-slate-300 max-h-32 overflow-auto">{JSON.stringify(r.output, null, 2)}</pre>
                      </div>
                    )}
                    {r.stdout && (
                      <div>
                        <div className="text-slate-500">stdout</div>
                        <pre className="bg-slate-950/60 border border-slate-700/40 rounded p-2 text-emerald-200 max-h-32 overflow-auto whitespace-pre-wrap">{r.stdout}</pre>
                      </div>
                    )}
                    {r.stderr && (
                      <div>
                        <div className="text-slate-500">stderr</div>
                        <pre className="bg-slate-950/60 border border-slate-700/40 rounded p-2 text-amber-200 max-h-32 overflow-auto whitespace-pre-wrap">{r.stderr}</pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'rose' | 'emerald' }) {
  const color = tone === 'rose' ? 'text-rose-300' : tone === 'emerald' ? 'text-emerald-300' : 'text-white';
  return (
    <div className="rounded-lg bg-slate-800/40 border border-slate-700/40 px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`text-base font-bold ${color} mt-0.5`}>{value}</div>
    </div>
  );
}
