'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Plug, Plus, Trash2, Edit3, RefreshCw, Loader2, X,
  CheckCircle2, AlertTriangle, Clock, Bot, Zap, PlayCircle,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import { AccessGate } from '@/components/layout/NoAccess';
import NextSteps from '@/components/shared/NextSteps';
import UnencryptedSecretsBanner from '@/components/shared/UnencryptedSecretsBanner';
import { describeTest, type TestResult } from './test-result';

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
  has_secret: boolean;
  needs_secret: boolean;
  secret_notice: string | null;
  config: Record<string, unknown>;
  is_active: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  created_at: string | null;
  updated_at: string | null;
  operations: string[];
}

// keep: the stored secret stays, replace: a new one is typed, remove: cleared on save
type SecretMode = 'keep' | 'replace' | 'remove';

interface FormState {
  id?: string;
  name: string;
  preset_key: string;
  kind: string;
  base_url: string;
  auth_type: string;
  secret: string;
  has_secret: boolean;
  needs_secret: boolean;
  secret_mode: SecretMode;
  config_text: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  preset_key: '',
  kind: 'cmms',
  base_url: '',
  auth_type: 'none',
  secret: '',
  has_secret: false,
  needs_secret: false,
  secret_mode: 'replace',
  config_text: '{}',
};

const LEGACY_NOTICE = "Re-enter this connector's secret, it used to point at an Abenix API key";

const KIND_OPTIONS = ['cmms', 'hris', 'telematics', 'standards', 'weather', 'cost_data', 'custom'];
const AUTH_OPTIONS = ['none', 'api_key', 'bearer', 'basic', 'oauth2'];
const KIND_LABELS: Record<string, string> = {
  cmms: 'Maintenance (CMMS)', hris: 'People (HRIS)', telematics: 'Telematics', standards: 'Standards',
  weather: 'Weather', cost_data: 'Cost data', custom: 'Other',
};
const AUTH_LABELS: Record<string, string> = {
  none: 'No sign-in', api_key: 'API key header', bearer: 'Bearer token', basic: 'Username and password', oauth2: 'OAuth 2 token',
};

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

function AdminConnectorsPage() {
  const [presets, setPresets] = useState<PresetSummary[]>([]);
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [firstConnector, setFirstConnector] = useState<Connector | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [pRes, cRes] = await Promise.all([
      apiFetch<PresetSummary[]>('/api/connectors/presets', { silent: true }),
      apiFetch<Connector[]>('/api/connectors', { silent: true }),
    ]);
    setPresets(pRes.data || []);
    setConnectors(cRes.data || []);
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

  const openCreate = () => { setForm(EMPTY_FORM); setFormError(null); setShowForm(true); };
  const openEdit = (c: Connector) => {
    setForm({
      id: c.id,
      name: c.name,
      preset_key: c.preset_key || '',
      kind: c.kind,
      base_url: c.base_url,
      auth_type: c.auth_type,
      secret: '',
      has_secret: c.has_secret,
      needs_secret: c.needs_secret,
      secret_mode: c.has_secret ? 'keep' : 'replace',
      config_text: JSON.stringify(c.config || {}, null, 2),
    });
    setFormError(null);
    setShowForm(true);
  };

  const submit = async () => {
    setSaving(true);
    let configJson: Record<string, unknown> | null = null;
    try {
      configJson = form.config_text.trim() ? JSON.parse(form.config_text) : {};
    } catch {
      setFormError('Config must be valid JSON, for example {} or {"auth_header_name": "X-Key"}.');
      setSaving(false);
      return;
    }
    setFormError(null);
    const payload: Record<string, unknown> = {
      name: form.name,
      kind: form.kind,
      preset_key: form.preset_key || null,
      base_url: form.base_url,
      auth_type: form.auth_type,
      config: configJson,
      is_active: true,
    };
    if (form.secret_mode === 'replace' && form.secret.trim()) payload.secret = form.secret;
    if (form.id && form.secret_mode === 'remove') payload.clear_secret = true;
    if (form.id) {
      const r = await apiFetch(`/api/connectors/${form.id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
        throwOnError: false,
      });
      if (r.error) { setFormError(r.error); setSaving(false); return; }
    } else {
      const wasEmpty = connectors.length === 0;
      const r = await apiFetch<Connector>('/api/connectors', {
        method: 'POST',
        body: JSON.stringify(payload),
        throwOnError: false,
      });
      if (r.error) { setFormError(r.error); setSaving(false); return; }
      if (wasEmpty && r.data?.id) setFirstConnector(r.data);
    }
    setSaving(false);
    setShowForm(false);
    setForm(EMPTY_FORM);
    await load();
  };

  const removeConnector = async (id: string) => {
    if (!confirm('Delete this connector? Agents using it will fail until reconfigured.')) return;
    const r = await apiFetch(`/api/connectors/${id}`, { method: 'DELETE', throwOnError: false });
    if (r.error) setError(`Could not delete the connector. ${r.error}`);
    await load();
  };

  const runTest = async (id: string) => {
    setTestingId(id);
    const res = await apiFetch<TestResult>(`/api/connectors/${id}/test`, { method: 'POST', throwOnError: false });
    if (res.data) setTestResults(r => ({ ...r, [id]: res.data! }));
    else setTestResults(r => ({ ...r, [id]: { ok: false, latency_ms: 0, status_code: null, sample_response_excerpt: null, error: res.error || 'The test could not run' } }));
    setTestingId(null);
    await load();
  };

  const presetOps = useMemo(() => {
    const p = presets.find(p => p.key === form.preset_key);
    return p?.operations || [];
  }, [presets, form.preset_key]);

  return (
    <div className="max-w-6xl mx-auto">
      <PageHeader
        className="mb-6"
        title="Connectors"
        purpose="Connect outside systems like maintenance, HR, telematics, weather or cost data so your agents can call them. For admins."
        icon={Plug}
        storageKey="admin-connectors"
        docSlug="02-runtime/14-connectors-and-triggers"
        primaryAction={{ label: 'New connector', icon: Plus, onClick: openCreate }}
        secondaryAction={{ label: 'Refresh', icon: RefreshCw, onClick: load, busy: loading }}
        steps={[
          'Click New connector, pick a preset if your system has one, and fill in its address.',
          'Add the key or password the system needs. It is never shown again, and is encrypted when the cluster has a data key set.',
          'Click Test to check the platform can reach the system.',
          'Agents with the connector call tool can then read from and write to it.',
        ]}
      />
      <UnencryptedSecretsBanner />

      {firstConnector && (
        <NextSteps
          className="mb-6"
          title={`${firstConnector.name} is added. What next?`}
          testId="connectors-next-steps"
          onDismiss={() => setFirstConnector(null)}
          steps={[
            {
              id: 'test',
              label: 'Test the connection',
              hint: 'Check the platform can reach it.',
              icon: PlayCircle,
              onClick: () => { void runTest(firstConnector.id); setFirstConnector(null); },
            },
            {
              id: 'agent',
              label: 'Build an agent with it',
              hint: 'Start an agent that already has the connector tool.',
              icon: Bot,
              href: '/builder?tool=connector_call',
            },
            {
              id: 'triggers',
              label: 'Add a trigger',
              hint: 'Run an agent on a schedule or a webhook.',
              icon: Zap,
              href: '/triggers',
            },
          ]}
        />
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
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
                <tr key={c.id} className="border-t border-slate-800/60" data-testid={`connector-row-${c.name}`}>
                  <td className="px-4 py-3 text-white">
                    <div className="font-medium">{c.name}</div>
                    {c.needs_secret && (
                      <p className="mt-1 max-w-xs whitespace-normal text-[11px] text-amber-300 flex items-start gap-1" data-testid={`connector-needs-secret-${c.name}`}>
                        <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" /> {c.secret_notice || LEGACY_NOTICE}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-300">{KIND_LABELS[c.kind] || c.kind}</td>
                  <td className="px-4 py-3 text-slate-400">{c.preset_key || '—'}</td>
                  <td className="px-4 py-3 text-slate-400 truncate max-w-xs"><code className="text-[11px]">{c.base_url}</code></td>
                  <td className="px-4 py-3 text-slate-400 text-xs">
                    <div className="flex items-center gap-1.5">
                      {okBadge && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                      {failBadge && <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />}
                      {!c.last_test_at && <Clock className="w-3.5 h-3.5 text-slate-600" />}
                      <span>{relTime(c.last_test_at)}</span>
                    </div>
                    {tr && (
                      <p className={`mt-1 max-w-xs whitespace-normal ${tr.ok ? 'text-emerald-300' : tr.blocked ? 'text-amber-300' : 'text-rose-300'}`} data-testid={`connector-test-result-${c.name}`}>
                        {describeTest(tr)}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => runTest(c.id)}
                        disabled={testingId === c.id}
                        aria-label={`Test ${c.name}`}
                        className="px-2 py-1 rounded-md bg-slate-700/50 hover:bg-slate-700 text-[11px] text-slate-200"
                      >
                        {testingId === c.id ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Test'}
                      </button>
                      <button
                        onClick={() => openEdit(c)}
                        className="p-1 rounded-md hover:bg-slate-700 text-slate-400 hover:text-white"
                        aria-label={`Edit ${c.name}`}
                        title="Edit"
                      >
                        <Edit3 className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={() => removeConnector(c.id)}
                        className="p-1 rounded-md hover:bg-rose-500/20 text-slate-400 hover:text-rose-300"
                        aria-label={`Delete ${c.name}`}
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
          <div role="dialog" aria-modal="true" aria-labelledby="connector-form-title" className="w-full max-w-2xl bg-[#0F172A] border border-slate-700 rounded-2xl shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
              <h2 id="connector-form-title" className="text-sm font-semibold text-white">{form.id ? 'Edit connector' : 'New connector'}</h2>
              <button onClick={() => setShowForm(false)} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
            </div>
            <div className="px-5 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
              <div>
                <label htmlFor="cn-preset" className="text-[10px] uppercase text-slate-500">Preset</label>
                <select
                  id="cn-preset"
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
                <label htmlFor="cn-name" className="text-[10px] uppercase text-slate-500">Name</label>
                <input
                  id="cn-name"
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  placeholder="Acme Maximo (Plant 4)"
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="cn-kind" className="text-[10px] uppercase text-slate-500">Kind</label>
                  <select
                    id="cn-kind"
                  value={form.kind}
                    onChange={e => setForm({ ...form, kind: e.target.value })}
                    className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white"
                  >
                    {KIND_OPTIONS.map(k => <option key={k} value={k}>{KIND_LABELS[k] || k}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="cn-auth" className="text-[10px] uppercase text-slate-500">Auth type</label>
                  <select
                    id="cn-auth"
                  value={form.auth_type}
                    onChange={e => setForm({ ...form, auth_type: e.target.value })}
                    className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white"
                  >
                    {AUTH_OPTIONS.map(k => <option key={k} value={k}>{AUTH_LABELS[k] || k}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label htmlFor="cn-url" className="text-[10px] uppercase text-slate-500">Base URL</label>
                <input
                  id="cn-url"
                  value={form.base_url}
                  onChange={e => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://acme.service-now.com/api/now"
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white font-mono placeholder-slate-600"
                />
              </div>
              <div>
                <label htmlFor="cn-secret" className="text-[10px] uppercase text-slate-500">Secret</label>
                {form.needs_secret && form.secret_mode !== 'remove' && (
                  <p role="status" data-testid="connector-form-needs-secret" className="mt-1 text-[11px] text-amber-300 flex items-start gap-1">
                    <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" /> {LEGACY_NOTICE}.
                  </p>
                )}
                {form.has_secret && form.secret_mode === 'keep' && (
                  <div className="mt-1 flex items-center gap-2" data-testid="connector-secret-saved">
                    <span className="flex-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-slate-400">Saved, hidden</span>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, secret_mode: 'replace', secret: '' })}
                      className="px-2.5 py-1.5 rounded-lg bg-slate-700/50 hover:bg-slate-700 text-[11px] text-slate-200"
                    >
                      Replace
                    </button>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, secret_mode: 'remove', secret: '' })}
                      className="px-2.5 py-1.5 rounded-lg hover:bg-rose-500/20 text-[11px] text-rose-300"
                    >
                      Remove
                    </button>
                  </div>
                )}
                {form.has_secret && form.secret_mode === 'remove' && (
                  <div className="mt-1 flex items-center gap-2">
                    <span className="flex-1 text-[11px] text-rose-300">The saved secret is removed when you save.</span>
                    <button
                      type="button"
                      onClick={() => setForm({ ...form, secret_mode: 'keep' })}
                      className="px-2.5 py-1.5 rounded-lg bg-slate-700/50 hover:bg-slate-700 text-[11px] text-slate-200"
                    >
                      Keep it
                    </button>
                  </div>
                )}
                {form.secret_mode === 'replace' && (
                  <div className="mt-1 flex items-center gap-2">
                    <input
                      id="cn-secret"
                      type="password"
                      autoComplete="new-password"
                      value={form.secret}
                      onChange={e => setForm({ ...form, secret: e.target.value })}
                      placeholder={form.has_secret ? 'New secret' : 'Token, API key or password'}
                      className="flex-1 min-w-0 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-600"
                    />
                    {form.has_secret && (
                      <button
                        type="button"
                        onClick={() => setForm({ ...form, secret_mode: 'keep', secret: '' })}
                        className="px-2.5 py-1.5 rounded-lg text-[11px] text-slate-300 hover:text-white"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                )}
                <p className="mt-1 text-[10px] text-slate-500">
                  {form.auth_type === 'none'
                    ? 'Not sent while the auth type is No sign-in.'
                    : 'Write-only, it is never shown again. Agents send it the way the auth type says.'}
                </p>
              </div>
              <div>
                <label htmlFor="cn-config" className="text-[10px] uppercase text-slate-500">Config JSON</label>
                <textarea
                  id="cn-config"
                  value={form.config_text}
                  onChange={e => setForm({ ...form, config_text: e.target.value })}
                  rows={6}
                  className="w-full mt-1 px-3 py-2 bg-slate-900/60 border border-slate-700 rounded-lg text-[11px] text-white font-mono"
                />
                <p className="mt-1 text-[10px] text-slate-500">Vendor-specific overrides — e.g. {'{ "auth_header_name": "maxauth", "username": "svc-account" }'}.</p>
              </div>
            </div>
            {formError && <p role="alert" data-testid="connector-form-error" className="px-5 pb-2 text-xs text-rose-300">{formError}</p>}
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

export default function AdminConnectorsPageGated() {
  return (
    <AccessGate
      title="Connectors"
      purpose="Connect outside systems like maintenance, HR, telematics, weather or cost data so your agents can call them. For admins."
      icon={Plug}
      need={{ feature: 'manage_settings' }}
      instead={{ text: 'Agents can still use the tools that are already set up, listed in the Tools Catalogue.', href: '/tools', label: 'Open the Tools Catalogue' }}
    >
      <AdminConnectorsPage />
    </AccessGate>
  );
}
