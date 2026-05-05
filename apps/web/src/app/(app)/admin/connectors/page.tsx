'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Plug, Plus, Trash2, Edit3, RefreshCw, Loader2, X,
  CheckCircle2, AlertTriangle, Clock,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface PresetSummary {
  key: string;
  label: string;
  kind: string;
  auth_type: string;
  base_url_template: string;
  operations: string[];
}

interface Connector {
  id: string;
  name: string;
  kind: string;
  preset_key: string | null;
  base_url: string;
  auth_type: string;
  secret_ref: string | null;
  config: Record<string, unknown>;
  is_active: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string | null;
  updated_at: string | null;
  operations: string[];
}

interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
}

interface TestResult {
  ok: boolean;
  latency_ms: number;
  status_code: number | null;
  sample_response_excerpt: string | null;
  error: string | null;
}

interface FormState {
  id?: string;
  name: string;
  preset_key: string;
  kind: string;
  base_url: string;
  auth_type: string;
  secret_ref: string;
  config_text: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  preset_key: '',
  kind: 'cmms',
  base_url: '',
  auth_type: 'none',
  secret_ref: '',
  config_text: '{}',
};

const KIND_OPTIONS = ['cmms', 'hris', 'telematics', 'standards', 'weather', 'cost_data', 'custom'];
const AUTH_OPTIONS = ['none', 'api_key', 'bearer', 'basic', 'oauth2'];

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function AdminConnectorsPage() {
  const [presets, setPresets] = useState<PresetSummary[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  const load = useCallback(async () => {
    setLoading(true);
    const [pRes, cRes, kRes] = await Promise.all([
      apiFetch<PresetSummary[]>('/api/connectors/presets', { silent: true }),
      apiFetch<Connector[]>('/api/connectors', { silent: true }),
      apiFetch<ApiKey[]>('/api/api-keys', { silent: true }),
    ]);
    setPresets(pRes.data || []);
    setConnectors(cRes.data || []);
    setApiKeys(kRes.data || []);
    if (cRes.error && !cRes.data) setError(cRes.error);
    else setError(null);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const onPickPreset = (key: string) => {
    const p = presets.find(p => p.key === key);
    setForm(f => ({
      ...f,
      preset_key: key,
      kind: p?.kind || f.kind,
      auth_type: p?.auth_type || f.auth_type,
      base_url: p?.base_url_template || f.base_url,
    }));
  };

  const openCreate = () => { setForm(EMPTY_FORM); setShowForm(true); };
  const openEdit = (c: Connector) => {
    setForm({
      id: c.id,
      name: c.name,
      preset_key: c.preset_key || '',
      kind: c.kind,
      base_url: c.base_url,
      auth_type: c.auth_type,
      secret_ref: c.secret_ref || '',
      config_text: JSON.stringify(c.config || {}, null, 2),
    });
    setShowForm(true);
  };

  const submit = async () => {
    setSaving(true);
    let configJson: Record<string, unknown> | null = null;
    try {
      configJson = form.config_text.trim() ? JSON.parse(form.config_text) : {};
    } catch {
      setError('Config must be valid JSON');
      setSaving(false);
      return;
    }
    const payload = {
      name: form.name,
      kind: form.kind,
      preset_key: form.preset_key || null,
      base_url: form.base_url,
      auth_type: form.auth_type,
      secret_ref: form.secret_ref || null,
      config: configJson,
      is_active: true,
    };
    if (form.id) {
      await apiFetch(`/api/connectors/${form.id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    } else {
      await apiFetch('/api/connectors', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    }
    setSaving(false);
    setShowForm(false);
    setForm(EMPTY_FORM);
    await load();
  };

  const removeConnector = async (id: string) => {
    if (!confirm('Delete this connector? Agents using it will fail until reconfigured.')) return;
    await apiFetch(`/api/connectors/${id}`, { method: 'DELETE' });
    await load();
  };

  const runTest = async (id: string) => {
    setTestingId(id);
    const res = await apiFetch<TestResult>(`/api/connectors/${id}/test`, { method: 'POST' });
    if (res.data) setTestResults(r => ({ ...r, [id]: res.data! }));
    setTestingId(null);
    await load();
  };

  const presetOps = useMemo(() => {
    const p = presets.find(p => p.key === form.preset_key);
    return p?.operations || [];
  }, [presets, form.preset_key]);

  return (
    <div className="max-w-6xl mx-auto">
      <header className="flex flex-wrap items-center gap-3 mb-6">
        <div className="w-10 h-10 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center">
          <Plug className="w-5 h-5 text-cyan-400" />
        </div>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-2xl font-bold text-white">Connectors</h1>
          <p className="text-sm text-slate-500">External systems your agents can call — CMMS, HRIS, telematics, weather, cost data.</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs text-slate-300 hover:text-white"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 text-xs font-medium hover:bg-cyan-500/30"
        >
          <Plus className="w-3.5 h-3.5" /> New connector
        </button>
      </header>

      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/40 text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th className="text-left px-4 py-2 font-medium">Name</th>
              <th className="text-left px-4 py-2 font-medium">Kind</th>
              <th className="text-left px-4 py-2 font-medium">Preset</th>
              <th className="text-left px-4 py-2 font-medium">Base URL</th>
              <th className="text-left px-4 py-2 font-medium">Last test</th>
              <th className="text-right px-4 py-2 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && connectors.length === 0 && (
              <tr><td colSpan={6} className="text-center py-10 text-slate-500"><Loader2 className="w-4 h-4 animate-spin inline mr-2" /> Loading</td></tr>
            )}
            {!loading && connectors.length === 0 && (
              <tr><td colSpan={6} className="text-center py-10 text-slate-500">No connectors yet. Click <span className="text-cyan-400">New connector</span> to add one.</td></tr>
            )}
            {connectors.map(c => {
              const tr = testResults[c.id];
              const okBadge = c.last_test_ok === true;
              const failBadge = c.last_test_ok === false;
              return (
                <tr key={c.id} className="border-t border-slate-800/60">
                  <td className="px-4 py-3 text-white">
                    <div className="font-medium">{c.name}</div>
                    <div className="text-[10px] font-mono text-slate-600">{c.id.slice(0, 8)}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-300">{c.kind}</td>
                  <td className="px-4 py-3 text-slate-400">{c.preset_key || '—'}</td>
                  <td className="px-4 py-3 text-slate-400 truncate max-w-xs"><code className="text-[11px]">{c.base_url}</code></td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    <div className="flex items-center gap-1.5">
                      {okBadge && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                      {failBadge && <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}
                      {!c.last_test_at && <Clock className="w-3.5 h-3.5 text-slate-600" />}
                      <span>{relTime(c.last_test_at)}</span>
                      {tr?.latency_ms !== undefined && <span className="text-slate-600">({tr.latency_ms}ms)</span>}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => runTest(c.id)}
                        disabled={testingId === c.id}
                        className="px-2 py-1 rounded-md bg-slate-700/50 hover:bg-slate-700 text-[11px] text-slate-200"
                      >
                        {testingId === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Test'}
                      </button>
                      <button
                        onClick={() => openEdit(c)}
                        className="p-1 rounded-md hover:bg-slate-700 text-slate-400 hover:text-white"
                        title="Edit"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => removeConnector(c.id)}
                        className="p-1 rounded-md hover:bg-rose-500/20 text-slate-400 hover:text-rose-300"
                        title="Delete"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {showForm && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowForm(false)}>
          <div className="w-full max-w-2xl bg-[#0F172A] border border-slate-700 rounded-2xl shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <h2 className="text-sm font-semibold text-white">{form.id ? 'Edit connector' : 'New connector'}</h2>
              <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-5 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
              <div>
                <label className="text-[10px] uppercase text-slate-500">Preset</label>
                <select
                  value={form.preset_key}
                  onChange={e => onPickPreset(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white"
                >
                  <option value="">Custom (no preset)</option>
                  {presets.map(p => (
                    <option key={p.key} value={p.key}>{p.label} ({p.kind})</option>
                  ))}
                </select>
                {presetOps.length > 0 && (
                  <p className="mt-1 text-[10px] text-slate-500">Operations: {presetOps.join(', ')}</p>
                )}
              </div>
              <div>
                <label className="text-[10px] uppercase text-slate-500">Name</label>
                <input
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  placeholder="Acme Maximo (Plant 4)"
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] uppercase text-slate-500">Kind</label>
                  <select
                    value={form.kind}
                    onChange={e => setForm({ ...form, kind: e.target.value })}
                    className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white"
                  >
                    {KIND_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
                  </select>
                </div>
                <div>
                  <label className="text-[10px] uppercase text-slate-500">Auth type</label>
                  <select
                    value={form.auth_type}
                    onChange={e => setForm({ ...form, auth_type: e.target.value })}
                    className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white"
                  >
                    {AUTH_OPTIONS.map(k => <option key={k} value={k}>{k}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="text-[10px] uppercase text-slate-500">Base URL</label>
                <input
                  value={form.base_url}
                  onChange={e => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://acme.service-now.com/api/now"
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white font-mono placeholder-slate-600"
                />
              </div>
              <div>
                <label className="text-[10px] uppercase text-slate-500">Secret (API key)</label>
                <select
                  value={form.secret_ref}
                  onChange={e => setForm({ ...form, secret_ref: e.target.value })}
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white"
                >
                  <option value="">No secret</option>
                  {apiKeys.map(k => (
                    <option key={k.id} value={k.id}>{k.name} ({k.key_prefix})</option>
                  ))}
                </select>
                {apiKeys.length === 0 && (
                  <p className="mt-1 text-[10px] text-amber-300">No API keys yet. Add one at Workspace → API Keys first.</p>
                )}
              </div>
              <div>
                <label className="text-[10px] uppercase text-slate-500">Config JSON</label>
                <textarea
                  value={form.config_text}
                  onChange={e => setForm({ ...form, config_text: e.target.value })}
                  rows={6}
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-[11px] text-white font-mono"
                />
                <p className="mt-1 text-[10px] text-slate-500">Vendor-specific overrides — e.g. {'{ "auth_header_name": "maxauth", "username": "svc-account" }'}.</p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-slate-800">
              <button
                onClick={() => setShowForm(false)}
                className="px-3 py-1.5 rounded-lg text-xs text-slate-300 hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={submit}
                disabled={saving || !form.name || !form.base_url}
                className="px-3 py-1.5 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 text-xs font-medium hover:bg-cyan-500/30 disabled:opacity-50 flex items-center gap-1.5"
              >
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {form.id ? 'Save changes' : 'Create connector'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
