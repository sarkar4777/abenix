'use client';

import React, { useCallback, useEffect, useState } from 'react';
import {
  Workflow, RefreshCw, ChevronDown, ChevronRight, Box, Cpu, Cog, Server,
} from 'lucide-react';
import { formatCount } from '@/lib/format-stats';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

type Node = {
  id: string;
  kind: 'agent' | 'tool' | 'control' | 'unknown';
  ref: string;
  where_it_runs: string;
  // agent-node-specific
  agent_runtime_pool?: string | null;
  agent_min_replicas?: number | null;
  agent_max_replicas?: number | null;
  agent_concurrency?: number | null;
  // tool-node-specific
  tool_pool?: string;
  tool_cache_ttl?: number;
  tool_qps_global?: number;
  tool_inflight_global?: number;
};

type Pipeline = {
  id: string;
  slug: string;
  name: string;
  runtime_pool?: string | null;
  min_replicas?: number | null;
  max_replicas?: number | null;
  concurrency_per_replica?: number | null;
  node_count: number;
  kind_counts: Record<string, number>;
  nodes: Node[];
};

const KIND_STYLE: Record<string, { bg: string; border: string; text: string; icon: any; label: string }> = {
  agent:   { bg: 'bg-violet-900/30', border: 'border-violet-600/50', text: 'text-violet-200', icon: Cpu,       label: 'Agent' },
  tool:    { bg: 'bg-cyan-900/30',   border: 'border-cyan-600/50',   text: 'text-cyan-200',   icon: Box,       label: 'Tool' },
  control: { bg: 'bg-slate-800/50',  border: 'border-slate-600/50',  text: 'text-slate-300',  icon: Cog,       label: 'Control' },
  unknown: { bg: 'bg-slate-900',     border: 'border-slate-700',     text: 'text-slate-400',  icon: Cog,       label: '—' },
};

const POOL_COLOR: Record<string, string> = {
  inline: 'bg-slate-700 text-slate-300',
  default: 'bg-emerald-700/40 text-emerald-300',
  chat: 'bg-cyan-700/40 text-cyan-300',
  'heavy-reasoning': 'bg-amber-700/40 text-amber-300',
  'long-running': 'bg-purple-700/40 text-purple-300',
  runtime: 'bg-purple-700/40 text-purple-300',
};

function PipelineScalingPage() {
  const [rows, setRows] = useState<Pipeline[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/admin/scaling/pipelines`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      const body = await res.json();
      setRows(body?.data || []);
      // Expand the first pipeline by default
      if ((body?.data || []).length > 0) {
        setExpanded({ [body.data[0].id]: true });
      }
    } catch (e: any) {
      setError(e?.message || 'load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <PageHeader
        className="mb-6"
        title="Pipeline scaling"
        purpose="See where each step of every pipeline runs, so you know which worker pool to grow when pipelines slow down. For admins."
        icon={Workflow}
        storageKey="admin-pipeline-scaling"
        docSlug="02-runtime/08-queue-scaling"
        primaryAction={{ label: 'Refresh', icon: RefreshCw, onClick: load, busy: loading }}
        secondaryAction={{ label: 'Agent pools', icon: Server, href: '/admin/scaling' }}
        steps={[
          'Each pipeline runs on its own worker pool, which grows and shrinks with its queue.',
          <span key="agent">
            Inside a pipeline, <span className="text-violet-300">agent steps</span> go to that agent&apos;s own pool.
          </span>,
          <span key="tool">
            <span className="text-cyan-300">Tool steps</span> pass through the tool limits for caching, rate and how many run at once.
          </span>,
          <span key="control">
            <span className="text-slate-200">Control steps</span> like branches and loops run on the pipeline&apos;s own worker.
          </span>,
        ]}
      />

      {error && <div className="mb-4 p-3 rounded-md bg-red-900/30 border border-red-700/50 text-red-200 text-sm">{error}</div>}

      <div className="space-y-3">
        {rows.map((p) => {
          const isOpen = !!expanded[p.id];
          return (
            <div key={p.id} className="rounded-lg border border-slate-800 bg-slate-900/40">
              <button
                className="w-full flex items-center justify-between p-4 hover:bg-slate-800/30"
                onClick={() => setExpanded({ ...expanded, [p.id]: !isOpen })}
              >
                <div className="flex items-center gap-3 flex-1 min-w-0">
                  {isOpen ? <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" /> : <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />}
                  <div className="text-left min-w-0">
                    <div className="font-medium text-slate-100 truncate">{p.name}</div>
                    <div className="text-xs text-slate-500 font-mono truncate">{p.slug}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-xs">
                  <span className={`px-2 py-0.5 rounded font-mono ${POOL_COLOR[p.runtime_pool || 'default'] || POOL_COLOR.default}`}>
                    pipeline pool: {p.runtime_pool || 'default'}
                  </span>
                  <span className="text-slate-400">
                    {(p.min_replicas ?? '?') + '–' + (p.max_replicas ?? '?')} replicas
                  </span>
                  <span className="text-slate-400">{p.node_count} nodes</span>
                  <span className="flex items-center gap-2">
                    {(['agent', 'tool', 'control'] as const).map((k) =>
                      (p.kind_counts[k] || 0) > 0 ? (
                        <span key={k} className={`px-1.5 py-0.5 rounded text-[10px] ${KIND_STYLE[k].bg} ${KIND_STYLE[k].text}`}>
                          {p.kind_counts[k]} {k}
                        </span>
                      ) : null
                    )}
                  </span>
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-slate-800 p-4 overflow-x-auto">
                  {/* Pipeline pod box */}
                  <div className="mb-4 rounded-lg border border-slate-700 bg-slate-900/60 p-3 inline-block">
                    <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
                      <Server className="w-3.5 h-3.5" />
                      Pipeline pod fleet
                    </div>
                    <div className="font-mono text-sm text-slate-100">
                      abenix-agent-runtime-{p.runtime_pool || 'default'}
                    </div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      KEDA scales {p.min_replicas ?? '?'} → {p.max_replicas ?? '?'} replicas on Redis stream depth
                    </div>
                  </div>

                  {/* DAG: linear strip of node cards with arrows */}
                  <div className="flex items-stretch gap-2 overflow-x-auto pb-2">
                    {p.nodes.map((n, i) => {
                      const style = KIND_STYLE[n.kind];
                      const Icon = style.icon;
                      return (
                        <React.Fragment key={n.id}>
                          <div
                            className={`flex-shrink-0 w-56 rounded-lg border ${style.border} ${style.bg} p-3 flex flex-col`}
                          >
                            <div className={`flex items-center gap-1.5 text-[10px] uppercase ${style.text} mb-1`}>
                              <Icon className="w-3 h-3" /> {style.label}
                            </div>
                            <div className="font-mono text-xs text-slate-100 mb-2 break-all">{n.id}</div>
                            <div className="text-[11px] text-slate-300 mb-2 font-mono">{n.ref}</div>

                            {n.kind === 'agent' && (
                              <div className="mt-auto text-[10px] space-y-0.5">
                                <div className="flex items-center justify-between">
                                  <span className="text-slate-500">pool</span>
                                  <span className={`px-1.5 py-0.5 rounded font-mono ${POOL_COLOR[n.agent_runtime_pool || 'default']}`}>
                                    {n.agent_runtime_pool || 'default'}
                                  </span>
                                </div>
                                <div className="flex items-center justify-between text-slate-400">
                                  <span>replicas</span>
                                  <span className="font-mono">{n.agent_min_replicas ?? '?'}–{n.agent_max_replicas ?? '?'}</span>
                                </div>
                                <div className="flex items-center justify-between text-slate-400">
                                  <span>concur</span>
                                  <span className="font-mono">{n.agent_concurrency ?? '?'}</span>
                                </div>
                              </div>
                            )}

                            {n.kind === 'tool' && (
                              <div className="mt-auto text-[10px] space-y-0.5">
                                <div className="flex items-center justify-between">
                                  <span className="text-slate-500">pool</span>
                                  <span className={`px-1.5 py-0.5 rounded font-mono ${POOL_COLOR[n.tool_pool || 'inline']}`}>
                                    {n.tool_pool || 'inline'}
                                  </span>
                                </div>
                                <div className="flex items-center justify-between text-slate-400">
                                  <span>qps</span>
                                  <span className={`font-mono ${n.tool_qps_global === 0 ? 'text-slate-600' : ''}`}>
                                    {n.tool_qps_global == null ? '—' : formatCount(n.tool_qps_global)}
                                  </span>
                                </div>
                                <div className="flex items-center justify-between text-slate-400">
                                  <span>inflight</span>
                                  <span className={`font-mono ${n.tool_inflight_global === 0 ? 'text-slate-600' : ''}`}>
                                    {n.tool_inflight_global == null ? '—' : formatCount(n.tool_inflight_global)}
                                  </span>
                                </div>
                                <div className="flex items-center justify-between text-slate-400">
                                  <span>cache</span>
                                  <span className="font-mono">
                                    {n.tool_cache_ttl == null
                                      ? <span className="text-slate-600">—</span>
                                      : n.tool_cache_ttl > 0
                                        ? `${n.tool_cache_ttl}s`
                                        : <span className="text-slate-600">off</span>}
                                  </span>
                                </div>
                              </div>
                            )}

                            {n.kind === 'control' && (
                              <div className="mt-auto text-[10px] text-slate-500">
                                runs in-process on pipeline pod
                              </div>
                            )}
                          </div>

                          {i < p.nodes.length - 1 && (
                            <div className="flex items-center text-slate-700 flex-shrink-0">
                              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor"><path d="M0 9h14l-4-4 1-1 6 6-6 6-1-1 4-4H0z"/></svg>
                            </div>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </div>

                  {/* Legend / "where to scale" hints */}
                  <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px]">
                    <div className="rounded border border-violet-700/40 bg-violet-900/20 p-2">
                      <div className="text-violet-300 mb-1 flex items-center gap-1"><Cpu className="w-3 h-3" /> Agent nodes</div>
                      <div className="text-slate-400">Each runs on its own runtime_pool. Tune in <a href="/admin/scaling" className="underline">/admin/scaling</a>.</div>
                    </div>
                    <div className="rounded border border-cyan-700/40 bg-cyan-900/20 p-2">
                      <div className="text-cyan-300 mb-1 flex items-center gap-1"><Box className="w-3 h-3" /> Tool nodes</div>
                      <div className="text-slate-400">Go through the cache/sem/qps gate. Tune in <a href="/admin/tool-scaling" className="underline">/admin/tool-scaling</a>.</div>
                    </div>
                    <div className="rounded border border-slate-700 bg-slate-900/40 p-2">
                      <div className="text-slate-300 mb-1 flex items-center gap-1"><Cog className="w-3 h-3" /> Control nodes</div>
                      <div className="text-slate-400">No separate scaling — they ride the pipeline pod itself.</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {rows.length === 0 && !loading && (
          <div className="p-8 text-center text-slate-500 border border-dashed border-slate-700 rounded-lg">
            No pipeline-mode agents found. Create one with <code className="bg-slate-800 px-1 rounded">mode: pipeline</code> in its seed.
          </div>
        )}
      </div>
    </div>
  );
}

export default function PipelineScalingPageGated() {
  return (
    <AccessGate
      title="Pipeline scaling"
      purpose="See where each step of every pipeline runs, so you know which worker pool to grow when pipelines slow down. For admins."
      icon={Workflow}
      need={{ admin: true }}
      instead={{ text: 'You can follow your own runs and how long they take on Executions.', href: '/executions', label: 'Open Executions' }}
    >
      <PipelineScalingPage />
    </AccessGate>
  );
}
