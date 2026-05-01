'use client';

import { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Brain, Upload, Trash2, Play, Loader2, CheckCircle2, AlertCircle,
  Cloud, Monitor, Copy, Server, ChevronDown, ChevronUp, Sparkles,
  FileCode2, Database, Tag, Clock, Cpu,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

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

export default function MLModelsPage() {
  const { data: models, mutate } = useApi<MLModel[]>('/api/ml-models');
  const [selected, setSelected] = useState<MLModel | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [deployType, setDeployType] = useState<'local' | 'k8s'>('local');
  const [predInput, setPredInput] = useState('{"features": [5.1, 3.5, 1.4, 0.2]}');
  const [predResult, setPredResult] = useState('');
  const [uploadName, setUploadName] = useState('');
  const [uploadDesc, setUploadDesc] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => mutate();

  const handleUpload = async () => {
    if (!uploadFile || !uploadName) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      fd.append('metadata', JSON.stringify({
        name: uploadName,
        description: uploadDesc,
        tags: [],
      }));
      await apiFetch<any>('/api/ml-models', { method: 'POST', body: fd, headers: {} });
      setUploadName(''); setUploadDesc(''); setUploadFile(null);
      refresh();
    } catch (e) {
      console.error(e);
    }
    setUploading(false);
  };

  const handleDeploy = async (modelId: string) => {
    setDeploying(true);
    try {
      await apiFetch<any>(`/api/ml-models/${modelId}/deploy`, {
        method: 'POST',
        body: JSON.stringify({ deployment_type: deployType, replicas: 1 }),
      });
      refresh();
      // Start polling deployment status until it's running or failed
      pollDeploymentStatus(modelId);
    } catch (e) {
      console.error(e);
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
    await apiFetch<any>(`/api/ml-models/${modelId}`, { method: 'DELETE' });
    setSelected(null);
    refresh();
  };

  const handleUndeploy = async (modelId: string) => {
    await apiFetch<any>(`/api/ml-models/${modelId}/undeploy`, { method: 'DELETE' });
    refresh();
  };

  const handleActivate = async (modelId: string) => {
    await apiFetch<any>(`/api/ml-models/${modelId}/activate`, { method: 'POST', body: '{}' });
    refresh();
  };

  const handleDeactivate = async (modelId: string) => {
    await apiFetch<any>(`/api/ml-models/${modelId}/deactivate`, { method: 'POST', body: '{}' });
    refresh();
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
                    <button key={m.id} onClick={() => setSelected(m)}
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
                    <div className="flex items-center gap-2">
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

                {/* Deploy */}
                {selected.status === 'ready' && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Server className="w-3.5 h-3.5 text-cyan-400" /> Deploy
                    </h3>
                    <div className="flex items-center gap-3 mb-3">
                      <button onClick={() => setDeployType('local')}
                        className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-colors ${deployType === 'local' ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300' : 'bg-slate-900/30 border border-slate-700 text-slate-400'}`}>
                        <Monitor className="w-3.5 h-3.5" /> Local (in-process)
                      </button>
                      <button onClick={() => setDeployType('k8s')}
                        className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium flex items-center justify-center gap-2 transition-colors ${deployType === 'k8s' ? 'bg-blue-500/10 border border-blue-500/30 text-blue-300' : 'bg-slate-900/30 border border-slate-700 text-slate-400'}`}>
                        <Cloud className="w-3.5 h-3.5" /> Kubernetes Pod
                      </button>
                    </div>
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

                {/* Test Inference */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                    <Play className="w-3.5 h-3.5 text-emerald-400" /> Test Inference
                  </h3>
                  <textarea value={predInput} onChange={e => setPredInput(e.target.value)} rows={3}
                    placeholder='{"features": [5.1, 3.5, 1.4, 0.2]}'
                    className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono placeholder-slate-500 focus:border-emerald-500 focus:outline-none resize-none mb-2" />
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
    </div>
  );
}
