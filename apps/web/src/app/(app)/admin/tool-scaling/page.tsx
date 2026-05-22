'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  Activity, RefreshCw, Database, Gauge, Zap, X, Save, AlertTriangle,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

type Row = {
  slug: string;
  enabled?: boolean;
  pool?: string;
  max_inflight_global?: number;
  max_inflight_per_tenant?: number;
  rate_limit_qps_global?: number;
  rate_limit_qps_per_tenant?: number;
  cache_ttl_seconds?: number;
  cache_scope?: string;
  circuit_breaker_threshold?: number;
  circuit_breaker_window_s?: number;
  circuit_breaker_cooldown_s?: number;
  timeout_seconds?: number;
  daily_budget_calls_per_tenant?: number;
  calls_24h?: number;
  avg_ms?: number;
  inflight_global?: number | null;
  breaker_state?: string | null;
  configured?: boolean;
};

export default function ToolScalingPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Row | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/admin/tool-runtime`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      const body = await res.json();
      setRows(body?.data || []);
    } catch (e: any) {
      setError(e?.message || 'load failed');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/api/admin/tool-runtime`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${getToken()}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(editing),
      });
      if (!res.ok) throw new Error(await res.text());
      setEditing(null);
      load();
    } catch (e: any) {
      setError(e?.message || 'save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-2">
            <Gauge className="w-6 h-6 text-cyan-400" /> Tool runtime scaling
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Per-tool cache, concurrency, rate-limit, circuit breaker, daily budget, and pool routing. Live for every direct SDK call, preset run, agent loop tool call, and pipeline step.
          </p>
        </div>
        <button
          onClick={load}
          className="px-3 py-1.5 text-sm rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1.5 border border-slate-700"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> refresh
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-md bg-red-900/30 border border-red-700/50 text-red-200 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      <div className="rounded-lg border border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/60 text-slate-400 text-[11px] uppercase">
            <tr>
              <th className="text-left px-3 py-2">Tool</th>
              <th className="text-right px-3 py-2">24h calls</th>
              <th className="text-right px-3 py-2">avg ms</th>
              <th className="text-right px-3 py-2">inflight</th>
              <th className="text-right px-3 py-2">cap (g/t)</th>
              <th className="text-right px-3 py-2">qps (g/t)</th>
              <th className="text-right px-3 py-2">cache</th>
              <th className="text-center px-3 py-2">pool</th>
              <th className="text-center px-3 py-2">state</th>
              <th className="text-right px-3 py-2">action</th>
            </tr>
          </thead>
          <tbody className="text-slate-200">
            {rows.map((r) => (
              <tr key={r.slug} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                <td className="px-3 py-2 font-mono text-cyan-300">{r.slug}</td>
                <td className="px-3 py-2 text-right">{r.calls_24h ?? 0}</td>
                <td className="px-3 py-2 text-right">{r.avg_ms ?? 0}</td>
                <td className="px-3 py-2 text-right text-emerald-300">{r.inflight_global ?? 0}</td>
                <td className="px-3 py-2 text-right text-slate-400 text-xs font-mono">{r.max_inflight_global ?? '—'}/{r.max_inflight_per_tenant ?? '—'}</td>
                <td className="px-3 py-2 text-right text-slate-400 text-xs font-mono">{r.rate_limit_qps_global ?? 0}/{r.rate_limit_qps_per_tenant ?? 0}</td>
                <td className="px-3 py-2 text-right text-slate-400 text-xs">{(r.cache_ttl_seconds ?? 0) > 0 ? `${r.cache_ttl_seconds}s ${r.cache_scope}` : '—'}</td>
                <td className="px-3 py-2 text-center">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase ${r.pool === 'runtime' ? 'bg-purple-900/40 text-purple-300' : 'bg-slate-700/40 text-slate-300'}`}>
                    {r.pool || 'inline'}
                  </span>
                </td>
                <td className="px-3 py-2 text-center">
                  <span className={`inline-block w-2 h-2 rounded-full ${
                    r.breaker_state === 'open' ? 'bg-red-400' :
                    r.breaker_state === 'half_open' ? 'bg-yellow-400' : 'bg-emerald-400'
                  }`} title={r.breaker_state || 'closed'} />
                </td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => setEditing({ ...r })}
                    className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600"
                  >Edit</button>
                </td>
              </tr>
            ))}
            {rows.length === 0 && !loading && (
              <tr><td colSpan={10} className="px-3 py-6 text-center text-slate-500">No tool configs yet. Make some calls — defaults will appear on the next refresh.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {editing && (
        <div className="fixed inset-0 bg-black/60 z-40 flex items-end md:items-center justify-center p-4" onClick={() => setEditing(null)}>
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold flex items-center gap-2"><Zap className="w-4 h-4 text-cyan-400" /> {editing.slug}</h2>
              <button onClick={() => setEditing(null)}><X className="w-5 h-5 text-slate-400" /></button>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <NumField label="Inflight cap (global)" value={editing.max_inflight_global ?? 0} onChange={(v) => setEditing({ ...editing, max_inflight_global: v })} hint="org-wide concurrent calls" />
              <NumField label="Inflight cap (per tenant)" value={editing.max_inflight_per_tenant ?? 0} onChange={(v) => setEditing({ ...editing, max_inflight_per_tenant: v })} hint="fairness ceiling" />
              <NumField label="QPS (global)" value={editing.rate_limit_qps_global ?? 0} onChange={(v) => setEditing({ ...editing, rate_limit_qps_global: v })} hint="0 = no limit" />
              <NumField label="QPS (per tenant)" value={editing.rate_limit_qps_per_tenant ?? 0} onChange={(v) => setEditing({ ...editing, rate_limit_qps_per_tenant: v })} hint="0 = no limit" />
              <NumField label="Cache TTL (sec)" value={editing.cache_ttl_seconds ?? 0} onChange={(v) => setEditing({ ...editing, cache_ttl_seconds: v })} hint="0 = no cache" />
              <SelectField label="Cache scope" value={editing.cache_scope ?? 'global'} options={['global', 'per_tenant']} onChange={(v) => setEditing({ ...editing, cache_scope: v })} hint="global for public data" />
              <NumField label="Breaker threshold" value={editing.circuit_breaker_threshold ?? 0} onChange={(v) => setEditing({ ...editing, circuit_breaker_threshold: v })} hint="failures to trip" />
              <NumField label="Breaker window (sec)" value={editing.circuit_breaker_window_s ?? 30} onChange={(v) => setEditing({ ...editing, circuit_breaker_window_s: v })} hint="rolling window" />
              <NumField label="Breaker cooldown (sec)" value={editing.circuit_breaker_cooldown_s ?? 60} onChange={(v) => setEditing({ ...editing, circuit_breaker_cooldown_s: v })} hint="open→half-open" />
              <NumField label="Timeout (sec)" value={editing.timeout_seconds ?? 30} onChange={(v) => setEditing({ ...editing, timeout_seconds: v })} hint="hard cap" />
              <NumField label="Daily budget (calls/tenant)" value={editing.daily_budget_calls_per_tenant ?? 0} onChange={(v) => setEditing({ ...editing, daily_budget_calls_per_tenant: v })} hint="cost backstop" />
              <SelectField label="Pool" value={editing.pool ?? 'inline'} options={['inline', 'runtime']} onChange={(v) => setEditing({ ...editing, pool: v })} hint="inline=api pod; runtime=worker fleet" />
              <SelectField label="Enabled" value={editing.enabled === false ? 'false' : 'true'} options={['true', 'false']} onChange={(v) => setEditing({ ...editing, enabled: v === 'true' })} hint="global kill switch" />
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button onClick={() => setEditing(null)} className="px-3 py-1.5 text-sm rounded bg-slate-800 hover:bg-slate-700">Cancel</button>
              <button onClick={save} disabled={saving} className="px-3 py-1.5 text-sm rounded bg-cyan-600 hover:bg-cyan-500 text-white flex items-center gap-1.5">
                <Save className="w-3.5 h-3.5" /> {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function NumField({ label, value, onChange, hint }: { label: string; value: number; onChange: (v: number) => void; hint?: string }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <input type="number" value={value} onChange={(e) => onChange(parseInt(e.target.value || '0', 10))} className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100" />
      {hint && <span className="text-[10px] text-slate-500">{hint}</span>}
    </label>
  );
}

function SelectField({ label, value, options, onChange, hint }: { label: string; value: string; options: string[]; onChange: (v: string) => void; hint?: string }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-slate-400">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-100">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      {hint && <span className="text-[10px] text-slate-500">{hint}</span>}
    </label>
  );
}
