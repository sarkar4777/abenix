'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Brain, Cpu, RefreshCw, AlertTriangle, Cloud, Sparkles,
  CheckCircle2, XCircle, Loader2, Trash2, Play, Pencil,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { AccessGate } from '@/components/layout/NoAccess';

interface MLModel {
  id: string;
  name: string;
  version: string;
  framework: string;
  description: string | null;
  status: string;
  is_active: boolean;
  file_size_bytes: number | null;
  tags: string[] | null;
  deployments: {
    id: string;
    deployment_type: string;
    status: string;
    endpoint_url: string | null;
  }[];
  created_at: string;
  updated_at?: string | null;
  last_invocation_at?: string | null;
}

interface LlmModel {
  value: string;
  label: string;
  provider: string;
  is_deprecated: boolean;
  input_per_m: number;
  output_per_m: number;
  capabilities: Record<string, boolean>;
  status: string;
  last_checked_at: string | null;
}

interface LlmListResp {
  models: LlmModel[];
}

const ML_STATUS_TONE: Record<string, string> = {
  ready:      'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  running:    'border-blue-500/40 bg-blue-500/10 text-blue-300',
  uploaded:   'border-amber-500/40 bg-amber-500/10 text-amber-300',
  validating: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  error:      'border-red-500/40 bg-red-500/10 text-red-300',
  stopped:    'border-slate-700/60 bg-slate-900/40 text-slate-300',
};

const LLM_STATUS_TONE: Record<string, string> = {
  available:   'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  unavailable: 'border-red-500/40 bg-red-500/10 text-red-300',
  degraded:    'border-amber-500/40 bg-amber-500/10 text-amber-300',
};

const PROVIDER_TONE: Record<string, string> = {
  anthropic: 'text-amber-300',
  openai:    'text-emerald-300',
  google:    'text-sky-300',
  azure:     'text-blue-300',
  other:     'text-slate-300',
};

function relTime(iso: string | null | undefined): string {
  if (!iso) return '—';
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

function capList(caps: Record<string, boolean> | undefined): string[] {
  if (!caps) return [];
  return Object.entries(caps).filter(([, v]) => v).map(([k]) => k);
}

function AdminModelsPage() {
  const [mlModels, setMlModels] = useState<MLModel[]>([]);
  const [llmModels, setLlmModels] = useState<LlmModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editing, setEditing] = useState<MLModel | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setErr(null);

    (async () => {
      const [ml, llm] = await Promise.all([
        apiFetch<MLModel[]>('/api/ml-models', { silent: true }),
        apiFetch<LlmListResp | LlmModel[]>('/api/llm-models', { silent: true }),
      ]);
      if (cancelled) return;

      if (ml.error && llm.error) {
        const lower = (ml.error || '').toLowerCase();
        if (lower.includes('403') || lower.includes('forbid')) {
          setErr('Only admins can see the models catalogue. Ask an admin if you need this.');
          setLoading(false);
          return;
        }
        setErr(ml.error || llm.error || 'Could not load models');
        setLoading(false);
        return;
      }

      setMlModels(ml.data || []);
      const llmList = Array.isArray(llm.data) ? llm.data : (llm.data?.models || []);
      setLlmModels(llmList);
      setLoading(false);
    })();

    return () => { cancelled = true; };
  }, [refreshKey]);

  const mlCounts = useMemo(() => {
    const c = { total: mlModels.length, deployed: 0, ready: 0, error: 0 };
    for (const m of mlModels) {
      if (m.status === 'ready') c.ready += 1;
      if (m.status === 'error') c.error += 1;
      if (m.deployments?.some((d) => d.status === 'running')) c.deployed += 1;
    }
    return c;
  }, [mlModels]);

  const llmCounts = useMemo(() => {
    const c = { total: llmModels.length, available: 0, degraded: 0, deprecated: 0 };
    for (const m of llmModels) {
      if (m.status === 'available') c.available += 1;
      if (m.status === 'degraded') c.degraded += 1;
      if (m.is_deprecated) c.deprecated += 1;
    }
    return c;
  }, [llmModels]);

  async function deployModel(id: string) {
    setBusyId(id);
    const r = await apiFetch(`/api/ml-models/${id}/deploy`, {
      method: 'POST',
      body: JSON.stringify({ deployment_type: 'local', replicas: 1 }),
    });
    if (r.error) toastError('Deploy failed', r.error);
    else { toastSuccess('Deploy started'); setRefreshKey((k) => k + 1); }
    setBusyId(null);
  }

  async function disableModel(id: string) {
    if (!confirm('Stop this model deployment? It can be re-deployed later.')) return;
    setBusyId(id);
    const r = await apiFetch(`/api/ml-models/${id}/undeploy`, { method: 'DELETE' });
    if (r.error) toastError('Disable failed', r.error);
    else { toastSuccess('Deployment stopped'); setRefreshKey((k) => k + 1); }
    setBusyId(null);
  }

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="admin-models">
      <PageHeader
        className="mb-6"
        title="Models"
        purpose="See every trained model in this workspace and every AI model the platform can call, and start or stop model deployments. For admins."
        icon={Brain}
        iconClassName="text-amber-300"
        storageKey="admin-models"
        docSlug="02-runtime/12-ml-models"
        primaryAction={{ label: 'Upload model', icon: Cloud, href: '/ml-models' }}
        secondaryAction={{
          label: 'Refresh',
          icon: RefreshCw,
          busy: loading,
          onClick: () => setRefreshKey((k) => k + 1),
          testId: 'models-refresh',
        }}
        steps={[
          'Trained models are uploaded on the ML Models page and listed here with their status.',
          'Deploy starts a model so agents can ask it for predictions. Disable shuts the deployment down.',
          'The AI model list shows each provider model with its price, abilities and whether it is still supported.',
        ]}
      />

      {err && (
        <div className="mb-4 p-4 rounded-xl border border-red-500/40 bg-red-500/10 text-red-300 text-sm flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-semibold mb-1">Couldn't load models</div>
            <div className="text-xs opacity-80">{err}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">ML models</div>
          <div className="text-2xl font-bold text-white">{mlCounts.total}</div>
          <div className="text-xs text-slate-400 mt-1">
            <span className="text-emerald-400">{mlCounts.ready} ready</span>
            {mlCounts.error > 0 && <span className="text-red-400"> · {mlCounts.error} error</span>}
          </div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Deployed</div>
          <div className="text-2xl font-bold text-white">{mlCounts.deployed}</div>
          <div className="text-xs text-slate-400 mt-1">running endpoints</div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">LLM models</div>
          <div className="text-2xl font-bold text-white">{llmCounts.total}</div>
          <div className="text-xs text-slate-400 mt-1">
            <span className="text-emerald-400">{llmCounts.available} available</span>
            {llmCounts.degraded > 0 && <span className="text-amber-400"> · {llmCounts.degraded} degraded</span>}
          </div>
        </div>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Deprecated</div>
          <div className="text-2xl font-bold text-white">{llmCounts.deprecated}</div>
          <div className="text-xs text-slate-400 mt-1">LLMs flagged for migration</div>
        </div>
      </div>

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <Brain className="w-4 h-4 text-amber-300" /> ML Models
        </h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-x-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Name</th>
                <th className="text-left px-3 py-2 font-medium">Version</th>
                <th className="text-left px-3 py-2 font-medium">Family</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-left px-3 py-2 font-medium">Last run</th>
                <th className="text-left px-3 py-2 font-medium">Capabilities</th>
                <th className="text-right px-3 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={7}>Loading…</td></tr>
              )}
              {!loading && mlModels.length === 0 && !err && (
                <tr>
                  <td className="px-3 py-6 text-slate-500 italic" colSpan={7}>
                    No ML models registered. <a className="text-amber-300 hover:underline" href="/ml-models">Upload one</a>.
                  </td>
                </tr>
              )}
              {mlModels.map((m) => {
                const tone = ML_STATUS_TONE[m.status] || ML_STATUS_TONE.stopped;
                const deployed = m.deployments?.some((d) => d.status === 'running');
                const caps: string[] = Array.from(new Set([
                  ...(m.framework ? [m.framework] : []),
                  ...(m.tags || []).slice(0, 4)
                ]));
                return (
                  <tr key={m.id} className="border-t border-slate-800/60 hover:bg-slate-800/30" data-testid={`ml-row-${m.name}`}>
                    <td className="px-3 py-2 align-top">
                      <div className="text-slate-200 font-medium">{m.name}</div>
                      {m.description && (
                        <div className="text-[10px] text-slate-500 truncate max-w-xs">{m.description}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400 font-mono align-top">{m.version || '—'}</td>
                    <td className="px-3 py-2 text-slate-400 font-mono align-top">{m.framework || '—'}</td>
                    <td className="px-3 py-2 align-top">
                      <span className={`inline-flex items-center text-[10px] px-2 py-0.5 rounded border ${tone} uppercase tracking-wider`}>
                        {m.status}
                      </span>
                      {deployed && (
                        <div className="mt-1">
                          <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded border border-blue-500/40 bg-blue-500/10 text-blue-300">
                            <Cloud className="w-3 h-3" /> deployed
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-slate-400 align-top">{relTime(m.last_invocation_at || m.updated_at || m.created_at)}</td>
                    <td className="px-3 py-2 align-top">
                      <div className="flex flex-wrap gap-1 max-w-xs">
                        {caps.length === 0 ? (
                          <span className="text-slate-500 italic">—</span>
                        ) : caps.map((c) => (
                          <span key={c} className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border border-slate-700/60 bg-slate-900/60 text-slate-300 font-mono">
                            {c}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right align-top">
                      <div className="inline-flex gap-1 justify-end">
                        <a
                          href={`/ml-models?id=${m.id}`}
                          className="px-2 py-1 rounded border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60 text-[10px] inline-flex items-center gap-1"
                          data-testid={`ml-view-${m.name}`}
                        >
                          View
                        </a>
                        <button
                          onClick={() => setEditing(m)}
                          className="px-2 py-1 rounded border border-slate-700/60 bg-slate-900/40 text-slate-300 hover:bg-slate-800/60 text-[10px] inline-flex items-center gap-1"
                          data-testid={`ml-edit-${m.name}`}
                        >
                          <Pencil className="w-3 h-3" /> Edit
                        </button>
                        {!deployed && m.status === 'ready' && (
                          <button
                            onClick={() => deployModel(m.id)}
                            disabled={busyId === m.id}
                            className="px-2 py-1 rounded border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 text-[10px] inline-flex items-center gap-1"
                            data-testid={`ml-deploy-${m.name}`}
                          >
                            {busyId === m.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                            Deploy
                          </button>
                        )}
                        {deployed && (
                          <button
                            onClick={() => disableModel(m.id)}
                            disabled={busyId === m.id}
                            className="px-2 py-1 rounded border border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20 text-[10px] inline-flex items-center gap-1"
                            data-testid={`ml-disable-${m.name}`}
                          >
                            {busyId === m.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                            Disable
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-200 mb-2 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-cyan-300" /> LLM Catalog
        </h2>
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 overflow-x-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="bg-slate-900/60 text-slate-400">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Model</th>
                <th className="text-left px-3 py-2 font-medium">Provider</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-right px-3 py-2 font-medium">Input $/M</th>
                <th className="text-right px-3 py-2 font-medium">Output $/M</th>
                <th className="text-left px-3 py-2 font-medium">Capabilities</th>
                <th className="text-left px-3 py-2 font-medium">Last checked</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={7}>Loading…</td></tr>
              )}
              {!loading && llmModels.length === 0 && !err && (
                <tr><td className="px-3 py-6 text-slate-500 italic" colSpan={7}>No LLM models in the catalog.</td></tr>
              )}
              {llmModels.map((m) => {
                const tone = LLM_STATUS_TONE[m.status] || LLM_STATUS_TONE.unavailable;
                const provTone = PROVIDER_TONE[m.provider] || PROVIDER_TONE.other;
                const caps = capList(m.capabilities);
                return (
                  <tr key={m.value} className="border-t border-slate-800/60 hover:bg-slate-800/30" data-testid={`llm-row-${m.value}`}>
                    <td className="px-3 py-2 align-top">
                      <div className="text-slate-200 font-medium">{m.label}</div>
                      <div className="text-[10px] text-slate-500 font-mono">{m.value}</div>
                    </td>
                    <td className={`px-3 py-2 font-mono align-top ${provTone}`}>{m.provider}</td>
                    <td className="px-3 py-2 align-top">
                      <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded border ${tone} uppercase tracking-wider`}>
                        {m.status === 'available'
                          ? <CheckCircle2 className="w-3 h-3" />
                          : m.status === 'degraded'
                            ? <AlertTriangle className="w-3 h-3" />
                            : <XCircle className="w-3 h-3" />}
                        {m.status}
                      </span>
                      {m.is_deprecated && (
                        <div className="mt-1">
                          <span className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300 uppercase tracking-wider">
                            deprecated
                          </span>
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300 align-top">${m.input_per_m.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right font-mono text-slate-300 align-top">${m.output_per_m.toFixed(2)}</td>
                    <td className="px-3 py-2 align-top">
                      <div className="flex flex-wrap gap-1 max-w-xs">
                        {caps.length === 0 ? (
                          <span className="text-slate-500 italic">—</span>
                        ) : caps.map((c) => (
                          <span key={c} className="inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border border-slate-700/60 bg-slate-900/60 text-slate-300 font-mono">
                            {c}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-slate-400 align-top">{relTime(m.last_checked_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <EditModelModal model={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setRefreshKey((k) => k + 1); }} />

      <p className="text-[11px] text-slate-500 mt-3">
        ML models from <code className="text-cyan-300">/api/ml-models</code>; LLM catalog from <code className="text-cyan-300">/api/llm-models</code>.
        Edit pricing in <a className="text-cyan-300 hover:underline" href="/admin/llm-pricing">LLM Pricing</a>;
        change defaults in <a className="text-cyan-300 hover:underline" href="/admin/llm-settings">Model Selection</a>.
      </p>
    </div>
  );
}

function EditModelModal({ model, onClose, onSaved }: { model: MLModel | null; onClose: () => void; onSaved: () => void }) {
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    if (model) { setDescription(model.description || ''); setTags((model.tags || []).join(', ')); setErr(''); }
  }, [model]);
  const save = async () => {
    if (!model) return;
    setSaving(true); setErr('');
    const r = await apiFetch(`/api/ml-models/${model.id}`, {
      method: 'PUT',
      throwOnError: false,
      body: JSON.stringify({ description: description.trim(), tags: tags.split(',').map((t) => t.trim()).filter(Boolean) }),
    });
    setSaving(false);
    if (r.error) { setErr(r.error); return; }
    toastSuccess('Model updated', `${model.name} v${model.version}`);
    onSaved();
  };
  return (
    <ResponsiveModal open={model !== null} onClose={onClose} title={model ? `Edit ${model.name} v${model.version}` : 'Edit model'} maxWidth="max-w-md">
      <div className="space-y-3" data-testid="ml-edit-modal">
        <label className="block text-xs text-slate-400">
          Description
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={2000} data-testid="ml-edit-description"
            className="mt-1 w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500" />
        </label>
        <label className="block text-xs text-slate-400">
          Tags, separated by commas
          <input value={tags} onChange={(e) => setTags(e.target.value)} data-testid="ml-edit-tags" placeholder="fraud, tabular"
            className="mt-1 w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500" />
        </label>
        {err && <p role="alert" className="text-xs text-red-400">{err}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancel</button>
          <button onClick={save} disabled={saving} data-testid="ml-edit-save" className="flex items-center gap-2 px-4 py-2 bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 text-sm rounded-lg hover:bg-cyan-500/30 disabled:opacity-50">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}

export default function AdminModelsPageGated() {
  return (
    <AccessGate
      title="Models"
      purpose="See every trained model in this workspace and every AI model the platform can call, and start or stop model deployments. For admins."
      icon={Brain}
      need={{ admin: true }}
      instead={{ text: 'You can train and deploy your own models on ML Models.', href: '/ml-models', label: 'Open ML Models' }}
    >
      <AdminModelsPage />
    </AccessGate>
  );
}
