'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  TrendingUp, RefreshCw, AlertTriangle, CheckCircle2, XCircle, Loader2,
  Plug, ExternalLink, Clock,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';

interface Connector {
  id: string;
  name: string;
  kind: string;
  preset_key: string | null;
  base_url: string;
  auth_type: string;
  secret_ref: string | null;
  is_active: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string | null;
  updated_at: string | null;
  operations?: string[];
}

interface TestResult {
  ok: boolean;
  latency_ms: number;
  status_code: number | null;
  sample_response_excerpt: string | null;
  error: string | null;
}

const MARKET_KINDS = new Set([
  'market-data', 'market_data',
  'yahoo', 'bloomberg', 'tavily', 'ember', 'entso-e', 'entsoe', 'eia',
  'edgar', 'companies-house', 'companies_house', 'refinitiv', 'iex',
  'alpha-vantage', 'alpha_vantage', 'polygon', 'quandl',
]);

const AUTH_TONE: Record<string, string> = {
  none:    'border-slate-700/60 bg-slate-900/40 text-slate-300',
  api_key: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  bearer:  'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  basic:   'border-amber-500/40 bg-amber-500/10 text-amber-300',
  oauth2:  'border-purple-500/40 bg-purple-500/10 text-purple-300',
};

function authLabel(auth: string): string {
  if (!auth || auth === 'none') return 'no_key';
  if (auth === 'oauth2') return 'oauth';
  return auth;
}

function relTime(iso: string | null): string {
  if (!iso) return 'never';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function statusOf(c: Connector): 'live' | 'unavailable' | 'unknown' {
  if (!c.is_active) return 'unavailable';
  if (c.last_test_ok === true) return 'live';
  if (c.last_test_ok === false) return 'unavailable';
  return 'unknown';
}

export default function MarketSourcesPage() {
  const router = useRouter();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    // Try the filtered endpoint first; otherwise pull all and filter client-side.
    const filtered = await apiFetch<Connector[]>('/api/connectors?kind=market-data', { silent: true });
    let rows: Connector[] | null = filtered.data || null;
    if (!rows || rows.length === 0) {
      const all = await apiFetch<Connector[]>('/api/connectors', { silent: true });
      if (all.error) {
        const lower = (all.error || '').toLowerCase();
        if (lower.includes('403') || lower.includes('forbid')) {
          toastError('Admin role required', 'You do not have permission to view market sources.');
          router.push('/dashboard');
          return;
        }
        setErr(all.error);
        setLoading(false);
        return;
      }
      rows = (all.data || []).filter((c) => MARKET_KINDS.has(c.kind) || c.name.toLowerCase().includes('market'));
    }
    setConnectors(rows || []);
    setLoading(false);
  }, [router]);

  useEffect(() => { load(); }, [load, refreshKey]);

  async function testConnector(id: string) {
    setTestingId(id);
    const r = await apiFetch<TestResult>(`/api/connectors/${id}/test`, { method: 'POST' });
    if (r.data) {
      setTestResults((prev) => ({ ...prev, [id]: r.data as TestResult }));
      if (r.data.ok) toastSuccess('Connector live', `${r.data.latency_ms}ms`);
      else toastError('Connector unavailable', r.data.error || `status ${r.data.status_code}`);
      await load();
    } else if (r.error) {
      toastError('Test failed', r.error);
    }
    setTestingId(null);
  }

  async function toggleActive(c: Connector) {
    const r = await apiFetch(`/api/connectors/${c.id}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: !c.is_active }),
    });
    if (r.error) toastError('Update failed', r.error);
    else { toastSuccess(c.is_active ? 'Disabled' : 'Enabled'); await load(); }
  }

  const liveCount = useMemo(() => connectors.filter((c) => statusOf(c) === 'live').length, [connectors]);
  const downCount = useMemo(() => connectors.filter((c) => statusOf(c) === 'unavailable').length, [connectors]);

  return (
    <div className="max-w-6xl mx-auto p-6" data-testid="admin-market-sources">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-500/10 ring-1 ring-emerald-500/40 flex items-center justify-center">
            <TrendingUp className="w-5 h-5 text-emerald-300" />
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500">Admin · platform</p>
            <h1 className="text-2xl font-bold text-white">Market Data Sources</h1>
            <p className="text-sm text-slate-400">Connectors that feed price, fundamentals, regulatory and energy data into the platform.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60"
            data-testid="market-sources-refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
          <a
            href="/admin/connectors"
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20"
          >
            Add connector <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </header>

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn't load market sources</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Registered</div>
          <div className="text-2xl font-bold text-white">{connectors.length}</div>
        </div>
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <div className="text-[10px] uppercase tracking-wider text-emerald-400 mb-1">Live</div>
          <div className="text-2xl font-bold text-emerald-300">{liveCount}</div>
        </div>
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-4">
          <div className="text-[10px] uppercase tracking-wider text-red-400 mb-1">Unavailable</div>
          <div className="text-2xl font-bold text-red-300">{downCount}</div>
        </div>
      </div>

      <section>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Name</th>
                <th className="text-left px-3 py-2 font-medium">Kind</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">Last fetch</th>
                <th className="text-left px-3 py-2 font-medium">Auth</th>
                <th className="text-right px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={6}>Loading…</td></tr>
              )}
              {!loading && connectors.length === 0 && !err && (
                <tr>
                  <td className="px-3 py-6 text-slate-500 italic" colSpan={6}>
                    No market-data connectors registered yet.{' '}
                    <a className="text-cyan-300 hover:underline" href="/admin/connectors">Add one</a>.
                  </td>
                </tr>
              )}
              {connectors.map((c) => {
                const status = statusOf(c);
                const auth = authLabel(c.auth_type);
                const result = testResults[c.id];
                return (
                  <tr key={c.id} className="border-t border-slate-800/60 hover:bg-slate-800/30" data-testid={`market-row-${c.name}`}>
                    <td className="px-3 py-2 text-slate-200 font-medium">
                      <span className="inline-flex items-center gap-2">
                        <Plug className="w-3.5 h-3.5 text-slate-500" />
                        {c.name}
                      </span>
                      {c.base_url && (
                        <div className="text-[10px] text-slate-500 font-mono mt-0.5 truncate max-w-xs">{c.base_url}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400 font-mono">{c.kind}</td>
                    <td className="px-3 py-2">
                      {status === 'live' && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 uppercase tracking-wider">
                          <CheckCircle2 className="w-3 h-3" /> live
                        </span>
                      )}
                      {status === 'unavailable' && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-red-500/40 bg-red-500/10 text-red-300 uppercase tracking-wider">
                          <XCircle className="w-3 h-3" /> unavailable
                        </span>
                      )}
                      {status === 'unknown' && (
                        <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border border-slate-700/60 bg-slate-900/40 text-slate-400 uppercase tracking-wider">
                          <Clock className="w-3 h-3" /> untested
                        </span>
                      )}
                      {result?.error && (
                        <div className="text-[10px] text-red-400/80 mt-1 truncate max-w-xs">{result.error}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400">{relTime(c.last_test_at)}</td>
                    <td className="px-3 py-2">
                      <span className={`inline-flex items-center text-[10px] px-2 py-0.5 rounded border ${AUTH_TONE[c.auth_type] || AUTH_TONE.none} uppercase tracking-wider font-mono`}>
                        {auth}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-flex gap-1 justify-end">
                        <button
                          onClick={() => testConnector(c.id)}
                          disabled={testingId === c.id}
                          className="px-2 py-1 rounded border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60 text-[10px] inline-flex items-center gap-1"
                          data-testid={`test-${c.name}`}
                        >
                          {testingId === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                          Test
                        </button>
                        <button
                          onClick={() => toggleActive(c)}
                          className={`px-2 py-1 rounded border text-[10px] ${
                            c.is_active
                              ? 'border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20'
                              : 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20'
                          }`}
                        >
                          {c.is_active ? 'Disable' : 'Enable'}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-[11px] text-slate-500 mt-3">
        Reads <code className="text-cyan-300">/api/connectors</code> and filters to the market-data family
        (yahoo, bloomberg, tavily, ember, entso-e, eia, edgar, companies-house, ...).
        Use <code className="text-cyan-300">/admin/connectors</code> for full CRUD.
      </p>
    </div>
  );
}
