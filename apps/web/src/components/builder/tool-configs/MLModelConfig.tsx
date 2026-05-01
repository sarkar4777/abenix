'use client';


import { useEffect, useState } from 'react';
import {
  Brain, CheckCircle2, AlertCircle, Cloud, Monitor,
  Loader2, Play, RefreshCw, ChevronDown,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';

interface MLModelInfo {
  id: string;
  name: string;
  version: string;
  framework: string;
  status: string;
  is_active: boolean;
  input_schema: any;
  output_schema: any;
  deployments: { deployment_type: string; status: string; endpoint_url: string | null }[];
}

interface MLModelConfigProps {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  ready:     { bg: 'bg-emerald-500/10', text: 'text-emerald-300' },
  deployed:  { bg: 'bg-blue-500/10',    text: 'text-blue-300' },
  running:   { bg: 'bg-blue-500/10',    text: 'text-blue-300' },
  stopped:   { bg: 'bg-slate-500/10',   text: 'text-slate-400' },
  error:     { bg: 'bg-red-500/10',     text: 'text-red-300' },
  uploading: { bg: 'bg-amber-500/10',   text: 'text-amber-300' },
};

const FRAMEWORK_ICONS: Record<string, string> = {
  sklearn: '🧪', pytorch: '🔥', onnx: '⚡', tensorflow: '🧠', xgboost: '🌲',
};

export default function MLModelConfig({ values, onChange }: MLModelConfigProps) {
  const [models, setModels] = useState<MLModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [deploying, setDeploying] = useState(false);
  const [checkResult, setCheckResult] = useState<any>(null);

  const selectedModel = (values.model_name as string) || '';
  const defaultOperation = (values.operation as string) || 'predict';

  // Fetch available models
  const loadModels = async () => {
    setLoading(true);
    try {
      const res = await apiFetch<MLModelInfo[]>('/api/ml-models');
      setModels(res.data || []);
    } catch { /* silent */ }
    setLoading(false);
  };

  useEffect(() => { loadModels(); }, []);

  // Check model readiness when selected
  useEffect(() => {
    if (!selectedModel) { setCheckResult(null); return; }
    (async () => {
      try {
        const res = await apiFetch<any>(`/api/ml-models/check/${selectedModel}`);
        setCheckResult(res.data);
      } catch { setCheckResult(null); }
    })();
  }, [selectedModel, models]);

  const handleDeploy = async (modelId: string) => {
    setDeploying(true);
    try {
      await apiFetch<any>(`/api/ml-models/${modelId}/deploy`, {
        method: 'POST',
        body: JSON.stringify({ deployment_type: 'local', replicas: 1 }),
      });
      await loadModels();
    } catch { /* silent */ }
    setDeploying(false);
  };

  // Group models by name for version display
  const modelNames = [...new Set(models.filter(m => m.status !== 'deleted').map(m => m.name))];
  const activeModels = models.filter(m => m.is_active && m.status === 'ready');

  const selectedModelObj = models.find(m => m.name === selectedModel && m.is_active);
  const hasDeployment = selectedModelObj?.deployments?.some(d => d.status === 'running');

  return (
    <div className="space-y-4">
      {/* Model Status Banner */}
      {selectedModel && checkResult && (
        <div className={`rounded-lg border p-3 ${
          checkResult.ready && checkResult.deployed
            ? 'border-emerald-500/30 bg-emerald-500/5'
            : checkResult.ready
            ? 'border-amber-500/30 bg-amber-500/5'
            : 'border-red-500/30 bg-red-500/5'
        }`}>
          <div className="flex items-center gap-2 mb-1">
            {checkResult.ready && checkResult.deployed ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            ) : checkResult.ready ? (
              <AlertCircle className="w-4 h-4 text-amber-400" />
            ) : (
              <AlertCircle className="w-4 h-4 text-red-400" />
            )}
            <span className="text-xs font-semibold text-white">
              {checkResult.ready && checkResult.deployed ? 'Ready & Deployed' :
               checkResult.ready ? 'Ready — Not Deployed' : 'Not Found'}
            </span>
          </div>
          <p className="text-[10px] text-slate-400">{checkResult.message}</p>
          {checkResult.active_version && (
            <p className="text-[10px] text-slate-500 mt-1">Active version: v{checkResult.active_version}</p>
          )}
        </div>
      )}

      {/* Model Selector */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <Brain className="w-3 h-3 text-purple-400" />
          <span className="font-mono text-slate-500">model_name</span>
          <span className="text-red-400 text-[8px]">required</span>
        </label>
        <select
          value={selectedModel}
          onChange={(e) => onChange({ ...values, model_name: e.target.value })}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-purple-500 appearance-none"
        >
          <option value="">Select a model...</option>
          {modelNames.map(name => {
            const active = models.find(m => m.name === name && m.is_active);
            const latest = models.find(m => m.name === name);
            const fw = latest?.framework || 'unknown';
            const ver = active?.version || latest?.version || '?';
            const icon = FRAMEWORK_ICONS[fw] || '📦';
            return (
              <option key={name} value={name}>
                {icon} {name} (v{ver}, {fw})
              </option>
            );
          })}
        </select>
        {modelNames.length === 0 && !loading && (
          <p className="text-[10px] text-amber-300 mt-1">
            No models registered. Upload one via the ML Models page (/ml-models).
          </p>
        )}
      </div>

      {/* Operation */}
      <div>
        <label className="flex items-center gap-1.5 text-[10px] text-slate-400 mb-1">
          <span className="font-mono text-slate-500">operation</span>
        </label>
        <select
          value={defaultOperation}
          onChange={(e) => onChange({ ...values, operation: e.target.value })}
          className="w-full px-3 py-2 bg-slate-900/50 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-purple-500"
        >
          <option value="predict">predict — Run inference</option>
          <option value="list_models">list_models — Show available models</option>
          <option value="get_model_info">get_model_info — Get schema & metadata</option>
        </select>
      </div>

      {/* Available Models List */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-[10px] text-slate-400 font-semibold uppercase tracking-wider">
            Available Models
          </label>
          <button onClick={loadModels} className="text-[10px] text-slate-500 hover:text-white flex items-center gap-1">
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
        {loading ? (
          <div className="flex justify-center py-4"><Loader2 className="w-4 h-4 animate-spin text-purple-400" /></div>
        ) : activeModels.length === 0 ? (
          <div className="rounded-lg border border-slate-700/50 bg-slate-900/30 p-3 text-center">
            <Brain className="w-6 h-6 text-purple-400/30 mx-auto mb-1" />
            <p className="text-[10px] text-slate-500">No active models.</p>
            <p className="text-[10px] text-slate-600">Upload via /ml-models page.</p>
          </div>
        ) : (
          <div className="space-y-1.5 max-h-48 overflow-y-auto">
            {activeModels.map(m => {
              const isDeployed = m.deployments?.some(d => d.status === 'running');
              const isSelected = m.name === selectedModel;
              const st = STATUS_COLORS[m.status] || STATUS_COLORS.ready;
              return (
                <div
                  key={m.id}
                  onClick={() => onChange({ ...values, model_name: m.name })}
                  className={`rounded-lg border p-2.5 cursor-pointer transition-colors ${
                    isSelected
                      ? 'border-purple-500/50 bg-purple-500/10'
                      : 'border-slate-700/50 bg-slate-900/20 hover:border-slate-600'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-white flex items-center gap-1.5">
                      <span>{FRAMEWORK_ICONS[m.framework] || '📦'}</span>
                      {m.name}
                      <span className="text-[9px] text-slate-500">v{m.version}</span>
                    </span>
                    <div className="flex items-center gap-1">
                      {m.is_active && (
                        <span className="px-1 py-0.5 rounded text-[8px] font-bold bg-emerald-500/20 text-emerald-300">ACTIVE</span>
                      )}
                      <span className={`px-1 py-0.5 rounded text-[8px] font-bold ${st.text} ${st.bg}`}>{m.status}</span>
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-[10px]">
                    <span className="text-slate-500">{m.framework}</span>
                    {isDeployed ? (
                      <span className="flex items-center gap-1 text-blue-300">
                        <Cloud className="w-3 h-3" /> Deployed
                      </span>
                    ) : (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeploy(m.id); }}
                        disabled={deploying}
                        className="flex items-center gap-1 text-amber-300 hover:text-amber-200"
                      >
                        {deploying ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                        Deploy
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Input Schema Preview */}
      {selectedModelObj?.input_schema && (
        <div>
          <label className="text-[10px] text-slate-400 mb-1 block">Input Schema</label>
          <pre className="rounded-lg bg-slate-900/80 border border-slate-700/50 p-2 text-[10px] text-slate-300 font-mono whitespace-pre-wrap max-h-24 overflow-y-auto">
            {JSON.stringify(selectedModelObj.input_schema, null, 2)}
          </pre>
        </div>
      )}

      {/* Pipeline Validation Info */}
      <div className="rounded-lg border border-slate-700/50 bg-slate-900/20 p-2.5">
        <p className="text-[10px] text-slate-500 leading-relaxed">
          <strong className="text-slate-400">Pipeline Validation:</strong> This tool requires a model to be uploaded
          and deployed before the pipeline can execute. Use the ML Models page (/ml-models) to upload a .pkl, .pt,
          or .onnx file, then deploy it (local or k8s).
        </p>
      </div>
    </div>
  );
}
