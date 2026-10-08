'use client';

import { useEffect, useMemo, useState } from 'react';
import { DollarSign, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { apiFetch, API_URL } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';

type PricingRow = {
  id: string;
  model: string;
  provider: 'anthropic' | 'openai' | 'google' | 'other';
  input_per_m: number;
  output_per_m: number;
  cached_input_per_m: number | null;
  batch_input_per_m: number | null;
  batch_output_per_m: number | null;
  effective_from: string | null;
  is_active: boolean;
  notes: string | null;
  updated_at: string | null;
};

type ApiResp = { rows: PricingRow[]; providers: string[] };

const PROVIDER_COLOR: Record<string, string> = {
  anthropic: 'text-amber-300',
  openai:    'text-emerald-300',
  google:    'text-sky-300',
  other:     'text-slate-300',
};

function LlmPricingPage() {
  const [data, setData] = useState<ApiResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, Partial<PricingRow>>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [newRow, setNewRow] = useState<Partial<PricingRow>>({
    provider: 'anthropic', is_active: true,
  });

  async function load() {
    setLoading(true); setErr(null);
    try {
      const r = await apiFetch<ApiResp>(`/api/admin/llm-pricing`);
      if (r.data) setData(r.data);
      else setErr(r.error?.toLowerCase().includes('403') ? 'Admin role required.' : (r.error || 'Load failed'));
    } catch (e: any) {
      setErr(e?.message || 'Load failed');
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  const byProvider = useMemo(() => {
    const buckets: Record<string, PricingRow[]> = { anthropic: [], openai: [], google: [], other: [] };
    (data?.rows || []).forEach((r) => { (buckets[r.provider] ||= []).push(r); });
    return buckets;
  }, [data]);

  function markEdit(id: string, patch: Partial<PricingRow>) {
    setPending((p) => ({ ...p, [id]: { ...(p[id] || {}), ...patch } }));
  }

  async function saveRow(id: string) {
    setSaving(id); setMsg(null);
    try {
      const r = await apiFetch<PricingRow>(`/api/admin/llm-pricing/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(pending[id] || {}),
      });
      if (r.error) setErr(r.error); else { setMsg('Saved. New rate applies to the next LLM call within 60s.'); await load(); setPending((p) => { const n = { ...p }; delete n[id]; return n; }); }
    } finally { setSaving(null); }
  }

  async function deleteRow(id: string, model: string) {
    if (!confirm(`Delete pricing for ${model}? The runtime will fall back to the hardcoded baseline.`)) return;
    setSaving(id);
    try {
      const r = await apiFetch(`/api/admin/llm-pricing/${id}`, { method: 'DELETE' });
      if (r.error) setErr(r.error); else await load();
    } finally { setSaving(null); }
  }

  async function createRow() {
    if (!newRow.model || newRow.input_per_m == null || newRow.output_per_m == null) {
      setErr('Enter a model id, an input price and an output price.'); return;
    }
    setAdding(true); setErr(null);
    try {
      const r = await apiFetch<PricingRow>(`/api/admin/llm-pricing`, {
        method: 'POST', body: JSON.stringify(newRow),
      });
      if (r.error) setErr(r.error); else { setNewRow({ provider: 'anthropic', is_active: true }); await load(); setMsg(`Added pricing for ${r.data?.model}.`); }
    } finally { setAdding(false); }
  }

  async function reseed() {
    if (!confirm('Re-seed from the baseline? Existing rows are kept; only missing models are added.')) return;
    setMsg(null); setErr(null);
    try {
      const r = await apiFetch<{ seeded: number }>(`/api/admin/llm-pricing/seed`, {
        method: 'POST', body: '{}',
      });
      if (r.error) setErr(r.error); else { setMsg(`Seeded ${r.data?.seeded ?? 0} new rows from baseline.`); await load(); }
    } catch (e: any) { setErr(e?.message || 'Seed failed'); }
  }

  async function seedDefaults() {
    setSeeding(true); setMsg(null); setErr(null);
    try {
      const r = await apiFetch<{ seeded: number }>(`/api/admin/llm-pricing/seed`, {
        method: 'POST', body: '{}',
      });
      if (r.error) setErr(r.error);
      else { setMsg(`Seeded ${r.data?.seeded ?? 0} rows from baseline.`); await load(); }
    } catch (e: any) { setErr(e?.message || 'Seed failed'); }
    finally { setSeeding(false); }
  }

  const focusAddRow = () => {
    const el = document.querySelector<HTMLInputElement>('[data-testid="add-pricing-row"] input');
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el?.focus();
  };

  if (loading) return <div className="p-6 text-slate-400">Loading pricing…</div>;
  if (err && !data) {
    return (
      <div className="p-6 max-w-2xl">
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
          <p className="font-semibold mb-1">Couldn’t load LLM pricing</p>
          <p className="text-rose-300/90">{err}</p>
          <button onClick={load} className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-100 text-xs">
            <RefreshCw className="w-3.5 h-3.5" /> Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6" data-testid="admin-llm-pricing">
      <PageHeader
        title="LLM Pricing"
        purpose="Set what each AI model costs per million tokens so spend and billing numbers are right. For admins."
        icon={DollarSign}
        iconClassName="text-emerald-400"
        storageKey="admin-llm-pricing"
        docSlug="09-reference/04-platform-settings"
        primaryAction={{ label: 'Add model pricing', icon: Plus, onClick: focusAddRow }}
        secondaryAction={{ label: 'Re-seed baseline', icon: RefreshCw, onClick: reseed }}
        extraActions={
          <button onClick={load} className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border border-slate-700/60 bg-slate-800/30 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800/60">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
        steps={[
          'Every model call is costed with the rates on this page, so spend and billing follow them.',
          'Edit a price and click Save. The new rate is used within a minute, with no redeploy.',
          'Add a row for a model that is missing, or re-seed to bring back any default models you deleted.',
          'Models with no row here fall back to the built in default prices.',
        ]}
      />

      {msg && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{msg}</div>}
      {err && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{err}</div>}

      {data && (data.rows?.length ?? 0) === 0 && (
        <div
          data-testid="pricing-empty-banner"
          className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-100 flex items-start justify-between gap-4"
        >
          <div>
            <p className="font-semibold text-amber-200">No pricing seeded for this tenant.</p>
            <p className="text-amber-200/80 mt-1">
              Cost rollups will fall back to the hardcoded baseline in
              <code className="px-1 py-0.5 mx-1 bg-amber-500/10 text-amber-100 rounded">llm_router.py</code>.
              Seed the platform defaults to make per-model rates editable here.
            </p>
          </div>
          <button
            onClick={seedDefaults}
            disabled={seeding}
            data-testid="seed-defaults-btn"
            className="shrink-0 px-3 py-2 rounded-lg bg-amber-400 hover:bg-amber-300 text-slate-950 text-sm font-semibold disabled:opacity-50 inline-flex items-center gap-2"
          >
            {seeding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            Seed defaults
          </button>
        </div>
      )}

      {/* New row */}
      <div className="rounded-xl border border-slate-700/60 bg-[#0B0F19] p-4" data-testid="add-pricing-row">
        <h2 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
          <Plus className="w-4 h-4 text-emerald-400" /> Add model pricing
        </h2>
        <div className="grid grid-cols-12 gap-3">
          <input aria-label="Model id" placeholder="model id (e.g. gpt-5)" className="col-span-3 bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
            value={newRow.model || ''} onChange={(e) => setNewRow({ ...newRow, model: e.target.value })} />
          <select aria-label="Provider" className="col-span-2 bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white"
            value={newRow.provider} onChange={(e) => setNewRow({ ...newRow, provider: e.target.value as any })}>
            {(data?.providers || ['anthropic', 'openai', 'google', 'other']).map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <input type="number" step="0.0001" aria-label="Price per million input tokens ($)" placeholder="input $/M" className="col-span-2 bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
            value={newRow.input_per_m ?? ''} onChange={(e) => setNewRow({ ...newRow, input_per_m: Number(e.target.value) })} />
          <input type="number" step="0.0001" aria-label="Price per million output tokens ($)" placeholder="output $/M" className="col-span-2 bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
            value={newRow.output_per_m ?? ''} onChange={(e) => setNewRow({ ...newRow, output_per_m: Number(e.target.value) })} />
          <input type="number" step="0.0001" aria-label="Price per million cached input tokens ($), optional" placeholder="cached (opt)" className="col-span-2 bg-slate-900/50 border border-slate-700/50 rounded px-3 py-2 text-sm text-white placeholder-slate-500"
            value={newRow.cached_input_per_m ?? ''} onChange={(e) => setNewRow({ ...newRow, cached_input_per_m: e.target.value === '' ? null : Number(e.target.value) })} />
          <button onClick={createRow} disabled={adding} aria-label="Add pricing" data-testid="add-pricing-submit" className="col-span-1 bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-sm font-semibold rounded-lg disabled:opacity-50 inline-flex items-center justify-center gap-1">
            {adding ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Per-provider tables */}
      {(['anthropic', 'openai', 'google', 'other'] as const).map((prov) => {
        const rows = byProvider[prov] || [];
        if (!rows.length) return null;
        return (
          <div key={prov} className="rounded-xl border border-slate-700/60 bg-[#0B0F19] overflow-hidden" data-testid={`provider-${prov}`}>
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between">
              <h3 className={`text-sm font-semibold ${PROVIDER_COLOR[prov]} uppercase tracking-wider`}>{prov}</h3>
              <span className="text-xs text-slate-500">{rows.length} {rows.length === 1 ? 'model' : 'models'}</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-800">
                  <th className="py-2 px-3 text-left">Model</th>
                  <th className="py-2 px-3 text-right">Input $/M</th>
                  <th className="py-2 px-3 text-right">Output $/M</th>
                  <th className="py-2 px-3 text-right">Cached $/M</th>
                  <th className="py-2 px-3 text-right">Batch in</th>
                  <th className="py-2 px-3 text-right">Batch out</th>
                  <th className="py-2 px-3"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const p = pending[r.id] || {};
                  const dirty = Object.keys(p).length > 0;
                  const show = (k: keyof PricingRow, override?: any) =>
                    (p as any)[k] ?? override ?? r[k];
                  return (
                    <tr key={r.id} className="border-b border-slate-800/60 hover:bg-slate-800/30" data-testid={`row-${r.model}`}>
                      <td className="py-2 px-3 font-mono text-white text-xs">{r.model}</td>
                      <td className="py-2 px-3 text-right">
                        <input type="number" step="0.0001" aria-label={`Input price for ${r.model}`} className="w-24 text-right bg-slate-900/50 border border-slate-700/40 rounded px-2 py-1 text-xs text-white font-mono"
                          value={show('input_per_m')} onChange={(e) => markEdit(r.id, { input_per_m: Number(e.target.value) })} />
                      </td>
                      <td className="py-2 px-3 text-right">
                        <input type="number" step="0.0001" aria-label={`Output price for ${r.model}`} className="w-24 text-right bg-slate-900/50 border border-slate-700/40 rounded px-2 py-1 text-xs text-white font-mono"
                          value={show('output_per_m')} onChange={(e) => markEdit(r.id, { output_per_m: Number(e.target.value) })} />
                      </td>
                      <td className="py-2 px-3 text-right">
                        <input type="number" step="0.0001" placeholder="—" aria-label={`Cached input price for ${r.model}`} className="w-24 text-right bg-slate-900/50 border border-slate-700/40 rounded px-2 py-1 text-xs text-white font-mono placeholder-slate-600"
                          value={show('cached_input_per_m', '') ?? ''} onChange={(e) => markEdit(r.id, { cached_input_per_m: e.target.value === '' ? null : Number(e.target.value) })} />
                      </td>
                      <td className="py-2 px-3 text-right text-slate-400 font-mono text-xs">{r.batch_input_per_m ?? '—'}</td>
                      <td className="py-2 px-3 text-right text-slate-400 font-mono text-xs">{r.batch_output_per_m ?? '—'}</td>
                      <td className="py-2 px-3 flex justify-end gap-1">
                        {dirty && (
                          <button onClick={() => saveRow(r.id)} disabled={saving === r.id}
                            data-testid={`save-${r.model}`}
                            aria-label={`Save pricing for ${r.model}`}
                            className="p-1.5 rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30">
                            {saving === r.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                          </button>
                        )}
                        <button onClick={() => deleteRow(r.id, r.model)} aria-label={`Delete pricing for ${r.model}`} className="p-1.5 rounded text-slate-500 hover:text-rose-400 hover:bg-rose-500/10">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}

      <div className="rounded-lg border border-slate-700/40 bg-slate-900/30 p-4 text-xs text-slate-400">
        <strong className="text-slate-200">How this is used:</strong> every model call is priced from this table, so run costs on
        Executions and Analytics use these rates. A model missing here is priced from the built-in list, and failing that at a
        cautious $3 input and $15 output per million tokens. Calls made on a Claude subscription are recorded at $0.
      </div>
    </div>
  );
}

export default function LlmPricingPageGated() {
  return (
    <AccessGate
      title="LLM Pricing"
      purpose="Set what each AI model costs per million tokens so spend and billing numbers are right. For admins."
      icon={DollarSign}
      need={{ feature: 'manage_settings' }}
      instead={{ text: 'Your own usage and spend are on Analytics.', href: '/analytics', label: 'Open Analytics' }}
    >
      <LlmPricingPage />
    </AccessGate>
  );
}
