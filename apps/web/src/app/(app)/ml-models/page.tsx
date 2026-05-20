'use client';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Brain, Upload, Trash2, Play, Loader2, CheckCircle2, AlertCircle,
  Cloud, Monitor, Copy, Server, ChevronDown, ChevronUp, Sparkles,
  FileCode2, Database, Tag, Clock, Cpu, Workflow, ArrowRight, Pencil,
  Share2,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';
import ResourceShareDialog from '@/components/share/ResourceShareDialog';
import InvocationsTable from '@/components/observability/InvocationsTable';

interface MLModel {
  id: string;
  name: string;
  version: string;
  framework: string;
  description: string | null;
  status: string;
  is_active: boolean;
  file_size_bytes: number | null;
  original_filename: string | null;
  input_schema: any;
  output_schema: any;
  training_metrics: any;
  tags: string[] | null;
  deployments: {
    id: string;
    deployment_type: string;
    status: string;
    endpoint_url: string | null;
  }[];
  created_at: string;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  uploaded:   { bg: 'bg-amber-500/10', text: 'text-amber-300', border: 'border-amber-500/30' },
  validating: { bg: 'bg-cyan-500/10',  text: 'text-cyan-300',  border: 'border-cyan-500/30' },
  ready:      { bg: 'bg-emerald-500/10', text: 'text-emerald-300', border: 'border-emerald-500/30' },
  error:      { bg: 'bg-red-500/10',   text: 'text-red-300',   border: 'border-red-500/30' },
  running:    { bg: 'bg-blue-500/10',  text: 'text-blue-300',  border: 'border-blue-500/30' },
  stopped:    { bg: 'bg-slate-500/10', text: 'text-slate-300', border: 'border-slate-500/30' },
};

const FRAMEWORK_ICONS: Record<string, string> = {
  sklearn: '🧪', pytorch: '🔥', onnx: '⚡', tensorflow: '🧠', xgboost: '🌲', custom: '📦',
};

function fmtBytes(bytes: number | null): string {
  if (!bytes) return '—';
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`;
  return `${bytes} B`;
}

function defaultInputFor(m: MLModel | null): string {
  if (!m) return '{"features": [5.1, 3.5, 1.4, 0.2]}';
  const ex = m.input_schema?.example;
  if (Array.isArray(ex)) return JSON.stringify({ features: ex });
  if (ex && typeof ex === 'object') return JSON.stringify(ex);
  const featList: string[] = Array.isArray(m.input_schema?.features) ? m.input_schema.features : [];
  if (featList.length > 0) return JSON.stringify({ features: featList.map(() => 0.0) });
  return '{"features": [5.1, 3.5, 1.4, 0.2]}';
}

export default function MLModelsPage() {
  const router = useRouter();
  const { data: models, mutate } = useApi<MLModel[]>('/api/ml-models');
  const [selected, setSelected] = useState<MLModel | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [deploying, setDeploying] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [deployType, setDeployType] = useState<'local' | 'k8s'>('local');
  const [deployReplicas, setDeployReplicas] = useState<number>(1);
  const [deployPreset, setDeployPreset] = useState<'small' | 'medium' | 'large'>('medium');
  const [predInput, setPredInput] = useState('{"features": [5.1, 3.5, 1.4, 0.2]}');
  const [predResult, setPredResult] = useState('');
  const [uploadName, setUploadName] = useState('');
  const [uploadDesc, setUploadDesc] = useState('');
  const [uploadInputSchema, setUploadInputSchema] = useState('');
  const [uploadOutputSchema, setUploadOutputSchema] = useState('');
  const [uploadSchemaError, setUploadSchemaError] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Edit-metadata panel state — populated when the user clicks Edit on the detail card.
  const [editing, setEditing] = useState(false);
  const [editDesc, setEditDesc] = useState('');
  const [editInputSchema, setEditInputSchema] = useState('');
  const [editOutputSchema, setEditOutputSchema] = useState('');
  const [editError, setEditError] = useState('');
  const [savingMeta, setSavingMeta] = useState(false);
  const [showShare, setShowShare] = useState(false);

  const refresh = () => mutate();

  useEffect(() => {
    if (selected) {
      setEditDesc(selected.description || '');
      setEditInputSchema(
        selected.input_schema ? JSON.stringify(selected.input_schema, null, 2) : '',
      );
      setEditOutputSchema(
        selected.output_schema ? JSON.stringify(selected.output_schema, null, 2) : '',
      );
      setEditError('');
      setEditing(false);
    }
  }, [selected?.id]);

  const handleUpload = async () => {
    if (!uploadFile || !uploadName) return;
    let inputSchemaParsed: any = undefined;
    let outputSchemaParsed: any = undefined;
    if (uploadInputSchema.trim()) {
      try { inputSchemaParsed = JSON.parse(uploadInputSchema); }
      catch (e: any) { setUploadSchemaError(`input_schema JSON: ${e.message}`); return; }
    }
    if (uploadOutputSchema.trim()) {
      try { outputSchemaParsed = JSON.parse(uploadOutputSchema); }
      catch (e: any) { setUploadSchemaError(`output_schema JSON: ${e.message}`); return; }
    }
    setUploadSchemaError('');
    setUploadError('');
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      const meta: Record<string, unknown> = {
        name: uploadName,
        description: uploadDesc,
        tags: [],
      };
      if (inputSchemaParsed !== undefined) meta.input_schema = inputSchemaParsed;
      if (outputSchemaParsed !== undefined) meta.output_schema = outputSchemaParsed;
      fd.append('metadata', JSON.stringify(meta));
      await apiFetch<any>('/api/ml-models', { method: 'POST', body: fd, headers: {} });
      setUploadName(''); setUploadDesc(''); setUploadFile(null);
      setUploadInputSchema(''); setUploadOutputSchema('');
      if (fileRef.current) fileRef.current.value = '';
      toastSuccess('Model uploaded', `${uploadName} is being validated`);
      refresh();
    } catch (e: any) {
      const msg = e?.message || 'Upload failed';
      setUploadError(msg);
      toastError('Upload failed', msg);
    }
    setUploading(false);
  };

  const handleSaveMeta = async () => {
    if (!selected) return;
    let inSchema: any = null;
    let outSchema: any = null;
    if (editInputSchema.trim()) {
      try { inSchema = JSON.parse(editInputSchema); }
      catch (e: any) { setEditError(`input_schema JSON: ${e.message}`); return; }
    }
    if (editOutputSchema.trim()) {
      try { outSchema = JSON.parse(editOutputSchema); }
      catch (e: any) { setEditError(`output_schema JSON: ${e.message}`); return; }
    }
    setEditError('');
    setSavingMeta(true);
    try {
      const res = await apiFetch<MLModel>(`/api/ml-models/${selected.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          description: editDesc,
          input_schema: inSchema,
          output_schema: outSchema,
        }),
      });
      if (res.data) setSelected(res.data);
      toastSuccess('Saved', 'Model metadata updated');
      setEditing(false);
      refresh();
    } catch (e: any) {
      const msg = e?.message || 'Save failed';
      setEditError(msg);
      toastError('Save failed', msg);
    }
    setSavingMeta(false);
  };

  const handleDeploy = async (modelId: string) => {
    setDeploying(true);
    try {
      const body: Record<string, unknown> = { deployment_type: deployType, replicas: deployReplicas };
      if (deployType === 'k8s') body.resource_preset = deployPreset;
      await apiFetch<any>(`/api/ml-models/${modelId}/deploy`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      const desc = deployType === 'k8s'
        ? `Polling ${deployReplicas}-replica ${deployPreset} k8s endpoint…`
        : 'In-process serving — ready immediately';
      toastSuccess('Deployment started', desc);
      refresh();
      // Start polling deployment status until it's running or failed
      pollDeploymentStatus(modelId);
    } catch (e: any) {
      toastError('Deploy failed', e?.message || 'Unknown error');
    }
    setDeploying(false);
  };

  // Async deployment status polling — updates in real-time even after navigating away
  const pollDeploymentStatus = (modelId: string) => {
    const poll = setInterval(async () => {
      try {
        const res = await apiFetch<MLModel>(`/api/ml-models/${modelId}`);
        const model = res.data;
        if (!model) { clearInterval(poll); return; }
        const deps = model.deployments || [];
        const deploying = deps.some(d => d.status === 'deploying');
        if (!deploying) {
          clearInterval(poll);
          refresh(); // final refresh to show running/failed status
          // Update selected if this is the current model
          if (selected?.id === modelId) {
            setSelected(model);
          }
        }
      } catch {
        clearInterval(poll);
      }
    }, 5000);
    // Auto-stop after 5 minutes
    setTimeout(() => clearInterval(poll), 300_000);
  };

  // On mount, check if any model has deploying status and start polling
  useEffect(() => {
    if (selected && selected.deployments?.some(d => d.status === 'deploying')) {
      pollDeploymentStatus(selected.id);
    }
  }, [selected?.id]);

  const handlePredict = async (modelId: string) => {
    setPredicting(true);
    setPredResult('');
    try {
      const input = JSON.parse(predInput);
      const res = await apiFetch<any>(`/api/ml-models/${modelId}/predict`, {
        method: 'POST',
        body: JSON.stringify({ input_data: input }),
      });
      setPredResult(JSON.stringify(res.data || res, null, 2));
    } catch (e: any) {
      setPredResult(`Error: ${e.message}`);
    }
    setPredicting(false);
  };

  const handleDelete = async (modelId: string) => {
    if (!confirm('Delete this model?')) return;
    try {
      await apiFetch<any>(`/api/ml-models/${modelId}`, { method: 'DELETE' });
      toastSuccess('Model deleted');
      setSelected(null);
      refresh();
    } catch (e: any) {
      toastError('Delete failed', e?.message || 'Unknown error');
    }
  };

  const handleUndeploy = async (modelId: string) => {
    try {
      await apiFetch<any>(`/api/ml-models/${modelId}/undeploy`, { method: 'DELETE' });
      toastSuccess('Undeployed');
      refresh();
    } catch (e: any) {
      toastError('Undeploy failed', e?.message || 'Unknown error');
    }
  };

  const handleActivate = async (modelId: string) => {
    try {
      await apiFetch<any>(`/api/ml-models/${modelId}/activate`, { method: 'POST', body: '{}' });
      toastSuccess('Activated', 'This version is now the default for agents');
      refresh();
    } catch (e: any) {
      toastError('Activate failed', e?.message || 'Unknown error');
    }
  };

  const handleDeactivate = async (modelId: string) => {
    try {
      await apiFetch<any>(`/api/ml-models/${modelId}/deactivate`, { method: 'POST', body: '{}' });
      toastSuccess('Deactivated');
      refresh();
    } catch (e: any) {
      toastError('Deactivate failed', e?.message || 'Unknown error');
    }
  };

  const handleUseInAgent = () => {
    if (!selected) return;
    router.push(`/builder?tool=ml_model&model_name=${encodeURIComponent(selected.name)}`);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-cyan-500/20 flex items-center justify-center">
              <Brain className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white flex items-center gap-2">
                ML Model Registry
                <Sparkles className="w-4 h-4 text-purple-400" />
              </h1>
              <p className="text-sm text-slate-400">Upload, deploy, and serve ML models inside agent workflows</p>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Left: Upload + List */}
          <div className="col-span-4 space-y-4">
            {/* Upload */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Upload className="w-3.5 h-3.5 text-purple-400" /> Upload Model
              </h3>
              <div className="space-y-2">
                <input type="text" value={uploadName} onChange={e => setUploadName(e.target.value)}
                  placeholder="Model name (e.g. iris-classifier)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none" />
                <input type="text" value={uploadDesc} onChange={e => setUploadDesc(e.target.value)}
                  placeholder="Description (optional)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none" />
                <div className="flex items-center gap-2">
                  <input ref={fileRef} type="file" accept=".pkl,.joblib,.pt,.pth,.onnx,.h5,.keras,.xgb"
                    onChange={e => setUploadFile(e.target.files?.[0] || null)} className="hidden" />
                  <button onClick={() => fileRef.current?.click()}
                    className="flex-1 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700 text-xs text-slate-400 hover:text-white hover:border-slate-600 transition-colors text-left truncate">
                    {uploadFile ? `📎 ${uploadFile.name}` : '📎 Choose model file (.pkl, .pt, .onnx...)'}
                  </button>
                </div>
                <details className="rounded-lg border border-slate-700/50 bg-slate-900/30">
                  <summary className="cursor-pointer px-2.5 py-1.5 text-[11px] text-slate-400 hover:text-white select-none">
                    Schemas (optional, recommended)
                  </summary>
                  <div className="p-2.5 space-y-2 border-t border-slate-700/50">
                    <p className="text-[10px] text-slate-500 leading-snug">
                      Agents introspect these to know what features to send. Skip and we'll try to infer from the model file, but explicit schemas are more reliable.
                    </p>
                    <div>
                      <label className="text-[10px] text-slate-500 uppercase mb-1 block">input_schema</label>
                      <textarea value={uploadInputSchema} onChange={e => { setUploadInputSchema(e.target.value); setUploadSchemaError(''); }}
                        rows={4} placeholder='{"features": ["age","income","tenure"], "example": [35, 50000, 24]}'
                        className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[10px] text-white font-mono placeholder-slate-600 focus:border-purple-500 focus:outline-none resize-y" />
                    </div>
                    <div>
                      <label className="text-[10px] text-slate-500 uppercase mb-1 block">output_schema</label>
                      <textarea value={uploadOutputSchema} onChange={e => { setUploadOutputSchema(e.target.value); setUploadSchemaError(''); }}
                        rows={3} placeholder='{"type":"regression","returns":"posterior mean + std"}'
                        className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[10px] text-white font-mono placeholder-slate-600 focus:border-purple-500 focus:outline-none resize-y" />
                    </div>
                  </div>
                </details>
                {uploadSchemaError && (
                  <p className="text-[10px] text-red-300 flex items-start gap-1"><AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /><span>{uploadSchemaError}</span></p>
                )}
                {uploadError && !uploadSchemaError && (
                  <p className="text-[10px] text-red-300 flex items-start gap-1"><AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /><span>{uploadError}</span></p>
                )}
                <button onClick={handleUpload} disabled={uploading || !uploadFile || !uploadName}
                  className="w-full px-3 py-2 rounded-lg bg-gradient-to-r from-purple-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-30 flex items-center justify-center gap-2 hover:shadow-lg hover:shadow-purple-500/20 transition-all">
                  {uploading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading...</> : <><Upload className="w-3.5 h-3.5" /> Upload & Validate</>}
                </button>
              </div>
            </div>

            {/* Model list */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Database className="w-3.5 h-3.5 text-cyan-400" /> Models ({(models || []).length})
              </h3>
              <div className="space-y-1 max-h-[50vh] overflow-y-auto">
                {(models || []).map(m => {
                  const st = STATUS_STYLES[m.status] || STATUS_STYLES.uploaded;
                  const isSelected = selected?.id === m.id;
                  return (
                    <button key={m.id} onClick={() => { setSelected(m); setPredInput(defaultInputFor(m)); setPredResult(''); }}
                      className={`w-full text-left px-3 py-2.5 rounded-lg text-xs transition-colors ${
                        isSelected ? 'bg-purple-500/10 border border-purple-500/30 text-white' : 'border border-transparent text-slate-400 hover:bg-slate-800/50 hover:text-white'
                      }`}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium flex items-center gap-1.5">
                          <span>{FRAMEWORK_ICONS[m.framework] || '📦'}</span>
                          {m.name}
                          {m.is_active && <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-emerald-500/20 text-emerald-300">ACTIVE</span>}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${st.text} ${st.bg}`}>{m.status}</span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-slate-500">
                        <span>v{m.version}</span>
                        <span>·</span>
                        <span>{m.framework}</span>
                        <span>·</span>
                        <span>{fmtBytes(m.file_size_bytes)}</span>
                      </div>
                    </button>
                  );
                })}
                {(models || []).length === 0 && (
                  <p className="text-xs text-slate-500 text-center py-6">No models uploaded yet</p>
                )}
              </div>
            </div>
          </div>

          {/* Right: Detail + Actions */}
          <div className="col-span-8 space-y-4">
            {!selected ? (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-12 text-center">
                <Brain className="w-12 h-12 text-purple-400/30 mx-auto mb-3" />
                <p className="text-sm text-slate-400">Select a model to view details, deploy, and test</p>
                <p className="text-xs text-slate-500 mt-1">Or upload a new model (.pkl, .joblib, .pt, .onnx, .h5)</p>
              </div>
            ) : (
              <>
                {/* Model header */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h2 className="text-lg font-bold text-white flex items-center gap-2">
                        <span>{FRAMEWORK_ICONS[selected.framework] || '📦'}</span>
                        {selected.name}
                        <span className="text-xs text-slate-500 font-normal">v{selected.version}</span>
                      </h2>
                      {selected.description && <p className="text-xs text-slate-400 mt-1">{selected.description}</p>}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <button onClick={handleUseInAgent}
                        className="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs hover:bg-cyan-500/20 transition-colors flex items-center gap-1"
                        data-testid="ml-use-in-agent">
                        <Workflow className="w-3 h-3" /> Use in Agent <ArrowRight className="w-3 h-3" />
                      </button>
                      <button onClick={() => setEditing(v => !v)}
                        className="px-3 py-1.5 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-300 text-xs hover:bg-slate-700/50 hover:text-white transition-colors flex items-center gap-1"
                        data-testid="ml-edit-metadata">
                        <Pencil className="w-3 h-3" /> {editing ? 'Cancel' : 'Edit metadata'}
                      </button>
                      <button onClick={() => setShowShare(true)}
                        className="px-3 py-1.5 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-300 text-xs hover:bg-slate-700/50 hover:text-white transition-colors flex items-center gap-1"
                        data-testid="ml-share">
                        <Share2 className="w-3 h-3" /> Share
                      </button>
                      {selected.is_active ? (
                        <button onClick={() => handleDeactivate(selected.id)}
                          className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs hover:bg-amber-500/20 transition-colors">
                          Deactivate
                        </button>
                      ) : (
                        <button onClick={() => handleActivate(selected.id)}
                          className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs hover:bg-emerald-500/20 transition-colors flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> Set Active
                        </button>
                      )}
                      <button onClick={() => handleDelete(selected.id)} className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs hover:bg-red-500/20 transition-colors flex items-center gap-1">
                        <Trash2 className="w-3 h-3" /> Delete Version
                      </button>
                    </div>
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Framework</p>
                      <p className="text-sm text-white font-medium capitalize">{selected.framework}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Status</p>
                      <p className={`text-sm font-medium capitalize ${(STATUS_STYLES[selected.status] || STATUS_STYLES.uploaded).text}`}>{selected.status}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Size</p>
                      <p className="text-sm text-white font-medium">{fmtBytes(selected.file_size_bytes)}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Deployments</p>
                      <p className="text-sm text-white font-medium">{selected.deployments?.length || 0}</p>
                    </div>
                  </div>
                  {selected.training_metrics && (
                    <div className="mt-3 rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase mb-1">Validation Info</p>
                      <pre className="text-xs text-slate-300 font-mono">{JSON.stringify(selected.training_metrics, null, 2)}</pre>
                    </div>
                  )}
                </div>

                {/* Edit metadata panel — collapsed unless "Edit metadata" is clicked */}
                {editing && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 space-y-3" data-testid="ml-edit-panel">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                      <Pencil className="w-3.5 h-3.5 text-cyan-400" /> Edit metadata
                    </h3>
                    <div>
                      <label className="text-[10px] text-slate-500 uppercase mb-1 block">Description</label>
                      <textarea value={editDesc} onChange={e => setEditDesc(e.target.value)} rows={2}
                        className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none resize-y" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[10px] text-slate-500 uppercase mb-1 block">input_schema (JSON)</label>
                        <textarea value={editInputSchema} onChange={e => { setEditInputSchema(e.target.value); setEditError(''); }}
                          rows={6}
                          className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[10px] text-white font-mono placeholder-slate-600 focus:border-cyan-500 focus:outline-none resize-y" />
                      </div>
                      <div>
                        <label className="text-[10px] text-slate-500 uppercase mb-1 block">output_schema (JSON)</label>
                        <textarea value={editOutputSchema} onChange={e => { setEditOutputSchema(e.target.value); setEditError(''); }}
                          rows={6}
                          className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[10px] text-white font-mono placeholder-slate-600 focus:border-cyan-500 focus:outline-none resize-y" />
                      </div>
                    </div>
                    {editError && (
                      <p className="text-[10px] text-red-300 flex items-start gap-1"><AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /><span>{editError}</span></p>
                    )}
                    <button onClick={handleSaveMeta} disabled={savingMeta}
                      className="px-4 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-semibold disabled:opacity-30 flex items-center gap-2 hover:bg-cyan-500/20 transition-colors"
                      data-testid="ml-save-metadata">
                      {savingMeta ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</> : <>Save metadata</>}
                    </button>
                  </div>
                )}

                {/* Deploy */}
                {selected.status === 'ready' && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Server className="w-3.5 h-3.5 text-cyan-400" /> Deploy
                    </h3>
                    <div className="flex items-center gap-3 mb-3">
                      <button onClick={() => setDeployType('local')}
                        className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-colors ${deployType === 'local' ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300' : 'bg-slate-900/30 border border-slate-700 text-slate-400'}`}
                        data-testid="deploy-type-local">
                        <Monitor className="w-3.5 h-3.5" /> Local (in-process)
                      </button>
                      <button onClick={() => setDeployType('k8s')}
                        className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-colors ${deployType === 'k8s' ? 'bg-blue-500/10 border border-blue-500/30 text-blue-300' : 'bg-slate-900/30 border border-slate-700 text-slate-400'}`}
                        data-testid="deploy-type-k8s">
                        <Cloud className="w-3.5 h-3.5" /> Kubernetes Pod
                      </button>
                    </div>
                    {deployType === 'k8s' && (
                      <div className="mb-3 grid grid-cols-2 gap-3 rounded-lg bg-slate-900/40 border border-slate-700/40 p-3" data-testid="k8s-deploy-config">
                        <div>
                          <label className="text-[10px] text-slate-500 uppercase mb-1 block">Replicas</label>
                          <input type="number" min={1} max={10} value={deployReplicas}
                            onChange={e => setDeployReplicas(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
                            className="w-full bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
                            data-testid="deploy-replicas-input" />
                          <p className="text-[9px] text-slate-600 mt-1">1–10. Each replica is an independent pod.</p>
                        </div>
                        <div>
                          <label className="text-[10px] text-slate-500 uppercase mb-1 block">Resource preset</label>
                          <select value={deployPreset}
                            onChange={e => setDeployPreset(e.target.value as 'small' | 'medium' | 'large')}
                            className="w-full bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
                            data-testid="deploy-preset-select">
                            <option value="small">Small — 100m / 256Mi · 500m / 1Gi cap</option>
                            <option value="medium">Medium — 250m / 512Mi · 1 / 2Gi cap</option>
                            <option value="large">Large — 500m / 1Gi · 2 / 4Gi cap</option>
                          </select>
                          <p className="text-[9px] text-slate-600 mt-1">CPU & memory request / limit per pod.</p>
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                      <button onClick={() => handleDeploy(selected.id)} disabled={deploying}
                        className="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-50 flex items-center gap-2 hover:shadow-lg hover:shadow-emerald-500/20 transition-all">
                        {deploying ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Deploying...</> : <><Play className="w-3.5 h-3.5" /> Deploy</>}
                      </button>
                      {selected.deployments?.some(d => d.status === 'running') && (
                        <button onClick={() => handleUndeploy(selected.id)}
                          className="px-3 py-2 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-400 text-xs hover:text-white transition-colors">
                          Undeploy
                        </button>
                      )}
                    </div>
                    {selected.deployments?.map(d => (
                      <div key={d.id} className="mt-2 rounded-lg bg-slate-900/50 p-2 flex items-center gap-2 text-[10px]">
                        {d.deployment_type === 'k8s' ? <Cloud className="w-3 h-3 text-blue-400" /> : <Monitor className="w-3 h-3 text-emerald-400" />}
                        <span className="text-slate-400">{d.deployment_type}</span>
                        <span className={`px-1 py-0.5 rounded ${(STATUS_STYLES[d.status] || STATUS_STYLES.stopped).text} ${(STATUS_STYLES[d.status] || STATUS_STYLES.stopped).bg}`}>{d.status}</span>
                        {d.endpoint_url && <span className="text-slate-500 font-mono truncate">{d.endpoint_url}</span>}
                      </div>
                    ))}
                  </div>
                )}

                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                    <Cpu className="w-3.5 h-3.5 text-cyan-400" /> Invocations
                  </h3>
                  <InvocationsTable kind="ml_model" resourceId={selected.id} />
                </div>

                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                    <Play className="w-3.5 h-3.5 text-emerald-400" /> Test Inference
                  </h3>
                  <textarea value={predInput} onChange={e => setPredInput(e.target.value)} rows={3}
                    placeholder={defaultInputFor(selected)}
                    className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono placeholder-slate-500 focus:border-emerald-500 focus:outline-none resize-none mb-2" />
                  {selected.input_schema?.features && Array.isArray(selected.input_schema.features) && (
                    <div className="mb-2 flex flex-wrap gap-1">
                      <span className="text-[10px] text-slate-500 mr-1">expected ({selected.input_schema.features.length}):</span>
                      {selected.input_schema.features.map((f: string) => (
                        <span key={f} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-300 border border-slate-700/50">{f}</span>
                      ))}
                    </div>
                  )}
                  <button onClick={() => handlePredict(selected.id)} disabled={predicting || selected.status !== 'ready'}
                    className="px-4 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs font-semibold disabled:opacity-30 flex items-center gap-2 hover:bg-emerald-500/20 transition-colors">
                    {predicting ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Predicting...</> : <><Play className="w-3.5 h-3.5" /> Run Prediction</>}
                  </button>
                  {predResult && (
                    <pre className="mt-3 rounded-lg bg-slate-900/80 border border-slate-700/50 p-3 text-xs text-emerald-300 font-mono whitespace-pre-wrap max-h-48 overflow-y-auto">{predResult}</pre>
                  )}
                </div>

                {/* Schemas */}
                {(selected.input_schema || selected.output_schema) && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                      <FileCode2 className="w-3.5 h-3.5 text-purple-400" /> Schemas
                    </h3>
                    <div className="grid grid-cols-2 gap-3">
                      {selected.input_schema && (
                        <div>
                          <p className="text-[10px] text-slate-500 uppercase mb-1">Input</p>
                          <pre className="rounded-lg bg-slate-900/80 p-2 text-[10px] text-slate-300 font-mono">{JSON.stringify(selected.input_schema, null, 2)}</pre>
                        </div>
                      )}
                      {selected.output_schema && (
                        <div>
                          <p className="text-[10px] text-slate-500 uppercase mb-1">Output</p>
                          <pre className="rounded-lg bg-slate-900/80 p-2 text-[10px] text-slate-300 font-mono">{JSON.stringify(selected.output_schema, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
      {selected && (
        <ResourceShareDialog
          open={showShare}
          onClose={() => setShowShare(false)}
          resourceType="ml_model"
          resourceId={selected.id}
          resourceName={`${selected.name} v${selected.version}`}
        />
      )}
    </div>
  );
}
