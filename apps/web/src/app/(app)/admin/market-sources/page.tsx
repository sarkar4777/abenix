'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  TrendingUp, RefreshCw, AlertTriangle, CheckCircle2, XCircle, Loader2,
  Plug, Plus, Clock, Trash2,
} from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';
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
  config?: Record<string, unknown>;
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
  const labels: Record<string, string> = { none: 'No key', api_key: 'API key', bearer: 'Token', basic: 'Password', oauth2: 'OAuth' };
  return labels[auth || 'none'] || auth;
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

const isMarket = (c: Connector) =>
  c.config?.category === 'market_data' || MARKET_KINDS.has(c.kind) || c.name.toLowerCase().includes('market');

function MarketSourcesPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Connector | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setErr(null);
    const all = await apiFetch<Connector[]>('/api/connectors', { silent: true });
    if (all.error) {
      setErr(all.error);
      setLoading(false);
      return;
    }
    setConnectors((all.data || []).filter(isMarket));
    setLoading(false);
  }, []);

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

  async function remove(c: Connector) {
    setRemoving(null);
    const r = await apiFetch(`/api/connectors/${c.id}`, { method: 'DELETE', throwOnError: false });
    if (r.error) toastError('Could not remove', r.error);
    else { toastSuccess('Source removed', c.name); await load(); }
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
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="admin-market-sources">
      <PageHeader
        className="mb-6"
        title="Market Data Sources"
        purpose="Check that the connectors feeding prices, company filings, regulatory and energy data are live, and switch them on or off. For admins."
        icon={TrendingUp}
        iconClassName="text-emerald-300"
        storageKey="admin-market-sources"
        docSlug="02-runtime/14-connectors-and-triggers"
        primaryAction={{ label: 'Add source', icon: Plus, onClick: () => setAdding(true), testId: 'market-add' }}
        secondaryAction={{
          label: 'Refresh',
          icon: RefreshCw,
          busy: loading,
          onClick: () => setRefreshKey((k) => k + 1),
          testId: 'market-sources-refresh',
        }}
        steps={[
          'Click Add source and give it a name and the address agents fetch from, with a key if it needs one.',
          'Click Test on a row to check it still answers. Live or unavailable is shown in the Status column.',
          'Disable a source to stop agents using it without deleting its settings, or Remove it for good.',
        ]}
      />

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn't load market sources</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 sm:gap-4 mb-6">
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
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
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
                    No market data sources yet.{' '}
                    <button className="text-cyan-300 hover:underline" onClick={() => setAdding(true)}>Add one</button>.
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
                    <td className="px-3 py-2 text-slate-400">{c.config?.category === 'market_data' ? 'market data' : c.kind.replace(/_/g, ' ')}</td>
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
                      <span className={`inline-flex items-center text-[10px] px-2 py-0.5 rounded border ${AUTH_TONE[c.auth_type] || AUTH_TONE.none} `}>
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
                        <button
                          onClick={() => setRemoving(c)}
                          aria-label={`Remove ${c.name}`}
                          data-testid={`remove-${c.name}`}
                          className="px-2 py-1 rounded border border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20 text-[10px] inline-flex items-center gap-1"
                        >
                          <Trash2 className="w-3 h-3" /> Remove
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

      <AddSourceModal open={adding} onClose={() => setAdding(false)} onAdded={async (c) => { setAdding(false); await load(); await testConnector(c.id); }} />
      <ConfirmModal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        onConfirm={() => { if (removing) void remove(removing); }}
        title={`Remove ${removing?.name ?? ''}?`}
        description="Agents can no longer fetch from it and its saved key is deleted. This cannot be undone."
        confirmLabel="Remove"
        variant="danger"
        confirmTestId="market-remove-confirm"
      />
    </div>
  );
}

function AddSourceModal({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: (c: Connector) => void }) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [auth, setAuth] = useState('none');
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => { if (open) { setName(''); setUrl(''); setAuth('none'); setSecret(''); setErr(''); } }, [open]);
  const save = async () => {
    if (!name.trim()) { setErr('Give it a name'); return; }
    if (!url.trim().toLowerCase().startsWith('https://')) { setErr('The address must start with https://'); return; }
    if (auth !== 'none' && !secret.trim()) { setErr('Paste the key, or choose No key'); return; }
    setBusy(true); setErr('');
    const r = await apiFetch<Connector>('/api/connectors', {
      method: 'POST',
      throwOnError: false,
      body: JSON.stringify({
        name: name.trim(), kind: 'custom', base_url: url.trim(), auth_type: auth,
        secret: auth === 'none' ? undefined : secret.trim(), config: { category: 'market_data' },
      }),
    });
    setBusy(false);
    if (r.error || !r.data) { setErr(r.error || 'Could not add the source'); return; }
    toastSuccess('Source added', `${r.data.name}, testing it now`);
    onAdded(r.data);
  };
  const field = 'mt-1 w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500';
  return (
    <ResponsiveModal open={open} onClose={onClose} title="Add a market data source" maxWidth="max-w-md">
      <div className="space-y-3" data-testid="market-add-modal">
        <label className="block text-xs text-slate-400">Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ECB exchange rates" className={field} data-testid="market-add-name" />
        </label>
        <label className="block text-xs text-slate-400">Address agents fetch from
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/v1" className={field} data-testid="market-add-url" />
        </label>
        <label className="block text-xs text-slate-400">Sign-in
          <select value={auth} onChange={(e) => setAuth(e.target.value)} className={field} data-testid="market-add-auth">
            <option value="none">No key</option>
            <option value="api_key">API key</option>
            <option value="bearer">Bearer token</option>
          </select>
        </label>
        {auth !== 'none' && (
          <label className="block text-xs text-slate-400">Key, stored encrypted and never shown again
            <input type="password" value={secret} onChange={(e) => setSecret(e.target.value)} className={field} data-testid="market-add-secret" />
          </label>
        )}
        {err && <p role="alert" className="text-xs text-red-400">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={save} disabled={busy} data-testid="market-add-save" className="flex items-center gap-2 px-4 py-2 bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-sm rounded-lg hover:bg-emerald-500/30 disabled:opacity-50">
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Add and test
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}

export default function MarketSourcesPageGated() {
  return (
    <AccessGate
      title="Market Data Sources"
      purpose="Check that the connectors feeding prices, company filings, regulatory and energy data are live, and switch them on or off. For admins."
      icon={TrendingUp}
      need={{ admin: true }}
    >
      <MarketSourcesPage />
    </AccessGate>
  );
}
