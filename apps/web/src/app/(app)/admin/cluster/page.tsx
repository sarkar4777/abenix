'use client';

import React, { useEffect, useState } from 'react';
import { Server, Cpu, HardDrive, Database, RefreshCw, ExternalLink, AlertTriangle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

const GRAFANA_ENV = (process.env.NEXT_PUBLIC_GRAFANA_URL || '').replace(/\/$/, '');

interface Node {
  name?: string;
  cpu_cores?: number;
  cpu_allocatable_cores?: number;
  mem_bytes?: number;
  mem_allocatable_bytes?: number;
  pods_capacity?: number;
  ready?: boolean;
  error?: string;
}
interface Disk { pvc: string; requested_bytes: number; capacity_bytes: number; status?: string; }
interface DB { bytes?: number; top_tables?: { name: string; bytes: number }[]; error?: string; }
interface Summary {
  nodes: Node[];
  pods: Record<string, number>;
  disks: Disk[];
  database: DB;
  k8s_source?: string;
  namespace?: string;
  grafana_url?: string;
}

function fmtBytes(n: number): string {
  if (!n) return '0';
  const units = ['B','KB','MB','GB','TB'];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

function Bar({ pct, tone = 'cyan' }: { pct: number; tone?: 'cyan' | 'amber' | 'red' }) {
  const clamped = Math.max(0, Math.min(100, pct));
  const color = clamped > 85 ? 'bg-red-500' : clamped > 70 ? 'bg-amber-500' : tone === 'red' ? 'bg-red-500' : 'bg-cyan-500';
  return (
    <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden">
      <div className={`h-full ${color}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}

export default function ClusterHealthPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    apiFetch<Summary>('/api/admin/cluster/summary', { silent: true })
      .then(({ data: payload, error }) => {
        if (cancelled) return;
        if (error) setErr(error);
        else if (payload) setData(payload);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const totalPods = data ? Object.values(data.pods).reduce((a, b) => a + b, 0) : 0;
  const runningPods = data?.pods?.Running ?? 0;
  const failedPods = (data?.pods?.Failed ?? 0) + (data?.pods?.Unknown ?? 0);

  return (
    <div className="max-w-6xl mx-auto p-6">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 ring-1 ring-cyan-500/40 flex items-center justify-center">
            <Server className="w-5 h-5 text-cyan-300" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Cluster Health</h1>
            <p className="text-sm text-slate-400">Node, pod, disk and DB pressure across the abenix namespace.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setRefreshKey(k => k + 1)}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60"
            data-testid="cluster-refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
          {(() => {
            const grafana = (data?.grafana_url || GRAFANA_ENV || '').replace(/\/$/, '');
            if (!grafana) return null;
            return (
              <a href={`${grafana}/?orgId=1`} target="_blank" rel="noreferrer"
                 className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20"
                 data-testid="cluster-grafana-link">
                Open Grafana <ExternalLink className="w-3 h-3" />
              </a>
            );
          })()}
        </div>
      </header>

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn't load cluster summary</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Pods</div>
          <div className="text-2xl font-bold text-white">{totalPods}</div>
          <div className="text-xs text-slate-400 mt-1">
            <span className="text-emerald-400">{runningPods} running</span>
            {failedPods > 0 && <span className="text-red-400"> · {failedPods} failed</span>}
          </div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Nodes</div>
          <div className="text-2xl font-bold text-white">{data?.nodes?.length ?? 0}</div>
          <div className="text-xs text-slate-400 mt-1">
            {data?.nodes?.length
              ? `${data.nodes.reduce((a, n) => a + (n.cpu_cores || 0), 0).toFixed(1)} total cores`
              : '—'}
          </div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Database</div>
          <div className="text-2xl font-bold text-white">{data?.database?.bytes != null ? fmtBytes(data.database.bytes) : '—'}</div>
          <div className="text-xs text-slate-400 mt-1">Top-{data?.database?.top_tables?.length ?? 0} tables below</div>
        </div>
      </div>

      <section className="mb-6">
        <h2 className="text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <Cpu className="w-4 h-4 text-cyan-300" /> Nodes
        </h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Name</th>
                <th className="text-left px-3 py-2 font-medium">CPU</th>
                <th className="text-left px-3 py-2 font-medium" colSpan={2}>Memory</th>
              </tr>
            </thead>
            <tbody>
              {(data?.nodes ?? []).filter(n => n.name).map(n => {
                const cap = n.cpu_cores || 0;
                const alloc = n.cpu_allocatable_cores || 0;
                const memCap = n.mem_bytes || 0;
                const memAlloc = n.mem_allocatable_bytes || 0;
                return (
                  <React.Fragment key={n.name}>
                    <tr className="border-t border-slate-800/60">
                      <td className="px-3 py-2 text-slate-300">
                        <span className="inline-flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${n.ready ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                          {n.name}
                        </span>
                      </td>
                      <td className="px-3 py-2 w-1/3 text-slate-400">
                        {cap.toFixed(0)} cores total · {alloc.toFixed(2)} allocatable
                      </td>
                      <td className="px-3 py-2 w-1/3 text-slate-400" colSpan={2}>
                        {fmtBytes(memCap)} total · {fmtBytes(memAlloc)} allocatable · {n.pods_capacity ?? 0} pod slots
                      </td>
                    </tr>
                    {n.error && (
                      <tr className="border-t border-red-500/20 bg-red-500/5" data-testid={`node-error-${n.name}`}>
                        <td className="px-3 py-2 text-red-300" colSpan={4}>
                          <span className="inline-flex items-start gap-2">
                            <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                            <span className="text-xs">{n.error}</span>
                          </span>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
              {!data?.nodes?.length && (
                <tr><td className="px-3 py-4 text-slate-500 italic" colSpan={4}>No node metrics — K8s API unreachable?</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <HardDrive className="w-4 h-4 text-cyan-300" /> Persistent Volumes
        </h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">PVC</th>
                <th className="text-left px-3 py-2 font-medium">Requested</th>
                <th className="text-left px-3 py-2 font-medium">Capacity</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {(data?.disks ?? []).map(d => (
                <tr key={d.pvc} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 text-slate-300">{d.pvc}</td>
                  <td className="px-3 py-2 text-slate-400">{fmtBytes(d.requested_bytes)}</td>
                  <td className="px-3 py-2 text-slate-400">{fmtBytes(d.capacity_bytes)}</td>
                  <td className="px-3 py-2 text-slate-400">{d.status || '—'}</td>
                </tr>
              ))}
              {!data?.disks?.length && (
                <tr><td className="px-3 py-4 text-slate-500 italic" colSpan={4}>No PVCs in this namespace.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-6">
        <h2 className="text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <Database className="w-4 h-4 text-cyan-300" /> Database — top tables
        </h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Table</th>
                <th className="text-left px-3 py-2 font-medium">Size</th>
              </tr>
            </thead>
            <tbody>
              {(data?.database?.top_tables ?? []).map(t => (
                <tr key={t.name} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 text-slate-300">{t.name}</td>
                  <td className="px-3 py-2 text-slate-400">{fmtBytes(t.bytes)}</td>
                </tr>
              ))}
              {!data?.database?.top_tables?.length && (
                <tr><td className="px-3 py-4 text-slate-500 italic" colSpan={2}>—</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-200 mb-2">Pods by phase</h2>
        <div className="flex flex-wrap gap-2">
          {Object.entries(data?.pods ?? {}).map(([phase, count]) => {
            const tone = phase === 'Running' ? 'emerald' : phase === 'Failed' ? 'red' : phase === 'Pending' ? 'amber' : 'slate';
            const cls = tone === 'emerald' ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
                      : tone === 'red'     ? 'border-red-500/40 bg-red-500/10 text-red-300'
                      : tone === 'amber'   ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
                      :                      'border-slate-700/60 bg-slate-900/40 text-slate-300';
            return (
              <span key={phase} className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border ${cls}`}>
                {phase} · <strong>{count}</strong>
              </span>
            );
          })}
          {!data?.pods || !Object.keys(data.pods).length && (
            <span className="text-xs text-slate-500 italic">No pod metrics available.</span>
          )}
        </div>
      </section>
    </div>
  );
}
