'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { mutate as swrMutate } from 'swr';
import {
  Brain, Upload, Trash2, Play, Loader2, CheckCircle2, AlertCircle,
  Cloud, Monitor, Server, Sparkles, ChevronDown, ChevronRight,
  FileCode2, Database, Cpu, Workflow, ArrowRight, Pencil, Info,
  Share2, FlaskConical, RotateCcw,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch, ApiError } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';
import ResourceShareDialog from '@/components/share/ResourceShareDialog';
import InvocationsTable from '@/components/observability/InvocationsTable';
import ConfirmModal from '@/components/ui/ConfirmModal';
import {
  type MLModel, RUNNABLE_EXTENSIONS, UNRUNNABLE_HINTS, FRAMEWORK_LABELS, INPUT_SCHEMA_TEMPLATE,
  fileExt, nextVersion, featureNames, featureCount, defaultInputFor, fmtBytes,
} from './helpers';

const LIST_KEY = '/api/ml-models';
const HOWTO_KEY = 'ml-models.howto.collapsed';

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  uploaded:   { bg: 'bg-amber-500/10', text: 'text-amber-300', label: 'Uploaded' },
  validating: { bg: 'bg-cyan-500/10', text: 'text-cyan-300', label: 'Checking' },
  ready:      { bg: 'bg-emerald-500/10', text: 'text-emerald-300', label: 'Ready' },
  error:      { bg: 'bg-red-500/10', text: 'text-red-300', label: 'Error' },
  running:    { bg: 'bg-blue-500/10', text: 'text-blue-300', label: 'Running' },
  deploying:  { bg: 'bg-cyan-500/10', text: 'text-cyan-300', label: 'Starting' },
  failed:     { bg: 'bg-red-500/10', text: 'text-red-300', label: 'Failed' },
  stopped:    { bg: 'bg-slate-500/10', text: 'text-slate-300', label: 'Stopped' },
};

const FRAMEWORK_ICONS: Record<string, string> = {
  sklearn: '🧪', pytorch: '🔥', onnx: '⚡', tensorflow: '🧠', xgboost: '🌲', custom: '📦',
};

const inputCls = 'w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:border-purple-500 focus:outline-none';
const btnGhost = 'px-3 py-1.5 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-300 text-xs hover:bg-slate-700/50 hover:text-white transition-colors flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed';

type PredOutcome = { ok: true; data: any } | { ok: false; message: string };

export default function MLModelsPage() {
  const router = useRouter();
  const { data: models, isLoading, error: listError } = useApi<MLModel[]>(LIST_KEY, {
    // keep polling while a k8s deployment is starting
    refreshInterval: (latest: any) =>
      Array.isArray(latest?.data) && latest.data.some((m: MLModel) => m.deployments?.some(d => d.status === 'deploying')) ? 4000 : 0,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useMemo(() => (models || []).find(m => m.id === selectedId) ?? null, [models, selectedId]);
  const detailRef = useRef<HTMLDivElement>(null);

  const [howtoOpen, setHowtoOpen] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [suggestedVersion, setSuggestedVersion] = useState('');
  const [uploadName, setUploadName] = useState('');
  const [uploadVersion, setUploadVersion] = useState('');
  const [uploadDesc, setUploadDesc] = useState('');
  const [uploadInputSchema, setUploadInputSchema] = useState('');
  const [uploadOutputSchema, setUploadOutputSchema] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [addingSample, setAddingSample] = useState(false);

  const [busy, setBusy] = useState<string | null>(null);
  const [deployType, setDeployType] = useState<'local' | 'k8s'>('local');
  const [deployReplicas, setDeployReplicas] = useState<number>(1);
  const [deployPreset, setDeployPreset] = useState<'small' | 'medium' | 'large'>('medium');
  const [predicting, setPredicting] = useState(false);
  const [predInput, setPredInput] = useState('');
  const [predOutcome, setPredOutcome] = useState<PredOutcome | null>(null);
  const [invocationsKey, setInvocationsKey] = useState(0);

  const [editing, setEditing] = useState(false);
  const [editDesc, setEditDesc] = useState('');
  const [editInputSchema, setEditInputSchema] = useState('');
  const [editOutputSchema, setEditOutputSchema] = useState('');
  const [editError, setEditError] = useState('');
  const [showShare, setShowShare] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const refresh = () => swrMutate(LIST_KEY);

  useEffect(() => {
    try { if (localStorage.getItem(HOWTO_KEY) === '1') setHowtoOpen(false); } catch { /* storage blocked */ }
  }, []);

  const toggleHowto = () => {
    const next = !howtoOpen;
    setHowtoOpen(next);
    try { localStorage.setItem(HOWTO_KEY, next ? '0' : '1'); } catch { /* storage blocked */ }
  };

  // reset per-model panels only when the selection changes, not on every refetch
  useEffect(() => {
    if (!selected) return;
    setEditDesc(selected.description || '');
    setEditInputSchema(selected.input_schema ? JSON.stringify(selected.input_schema, null, 2) : '');
    setEditOutputSchema(selected.output_schema ? JSON.stringify(selected.output_schema, null, 2) : '');
    setEditError('');
    setEditing(false);
    setPredInput(defaultInputFor(selected));
    setPredOutcome(null);
  }, [selected?.id]);

  const selectModel = (id: string) => {
    setSelectedId(id);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      setTimeout(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    }
  };

  const versionsFor = (name: string) => (models || []).filter(m => m.name === name.trim()).map(m => m.version);
  const versionPlaceholder = uploadName.trim() ? nextVersion(versionsFor(uploadName)) : '1.0.0';
  const pickedExt = uploadFile ? fileExt(uploadFile.name) : '';
  const fileHint = pickedExt && !RUNNABLE_EXTENSIONS.includes(pickedExt)
    ? (UNRUNNABLE_HINTS[pickedExt] || `Abenix cannot run ${pickedExt} files. Upload .joblib or .pkl (scikit-learn, XGBoost), .onnx, or .pt/.pth (PyTorch).`)
    : '';

  const onPickFile = (f: File | null) => {
    setUploadFile(f);
    setUploadError('');
    if (f && !uploadName.trim()) {
      setUploadName(f.name.replace(/\.[^.]+$/, '').replace(/[^A-Za-z0-9_.-]+/g, '-'));
    }
  };

  const parseJsonField = (raw: string, label: string): { ok: boolean; value?: any } => {
    if (!raw.trim()) return { ok: true, value: undefined };
    try {
      const v = JSON.parse(raw);
      if (!v || typeof v !== 'object' || Array.isArray(v)) {
        setUploadError(`${label} must be a JSON object, like {"features": [...]}`);
        return { ok: false };
      }
      return { ok: true, value: v };
    } catch (e: any) {
      setUploadError(`${label} is not valid JSON: ${e.message}`);
      return { ok: false };
    }
  };

  const handleUpload = async () => {
    if (!uploadFile || !uploadName.trim() || fileHint) return;
    setUploadError('');
    setSuggestedVersion('');
    const ins = parseJsonField(uploadInputSchema, 'Inputs');
    if (!ins.ok) return;
    const outs = parseJsonField(uploadOutputSchema, 'Outputs');
    if (!outs.ok) return;
    setUploading(true);
    const name = uploadName.trim();
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      const meta: Record<string, unknown> = { name, description: uploadDesc, tags: [] };
      if (uploadVersion.trim()) meta.version = uploadVersion.trim();
      if (ins.value !== undefined) meta.input_schema = ins.value;
      if (outs.value !== undefined) meta.output_schema = outs.value;
      fd.append('metadata', JSON.stringify(meta));
      const res = await apiFetch<MLModel>('/api/ml-models', { method: 'POST', body: fd, headers: {} });
      const created = res.data;
      setUploadName(''); setUploadVersion(''); setUploadDesc(''); setUploadFile(null);
      setUploadInputSchema(''); setUploadOutputSchema('');
      if (fileRef.current) fileRef.current.value = '';
      await refresh();
      if (created) {
        selectModel(created.id);
        toastSuccess('Model ready', `${created.name} v${created.version} loaded. Try a prediction below.`);
      }
    } catch (e: any) {
      const msg = e?.message || 'Upload failed';
      setUploadError(msg);
      if (e instanceof ApiError) {
        if (e.errorCode === 'VERSION_EXISTS' && typeof e.details?.next_version === 'string') {
          setSuggestedVersion(e.details.next_version);
        }
        const failed = e.details?.model as MLModel | undefined;
        if (e.errorCode === 'MODEL_LOAD_FAILED' && failed?.id) {
          await refresh();
          setSelectedId(failed.id);
        }
      }
      toastError('Upload failed', msg);
    }
    setUploading(false);
  };

  const handleTrySample = async () => {
    setAddingSample(true);
    try {
      const res = await apiFetch<MLModel>('/api/ml-models/samples/iris', { method: 'POST', body: '{}' });
      await refresh();
      if (res.data) {
        selectModel(res.data.id);
        setPredInput(defaultInputFor(res.data));
        setPredOutcome(null);
        toastSuccess('Sample model added', `${res.data.name} is ready. Press Run Prediction to try it.`);
      }
    } catch (e: any) {
      toastError('Could not add the sample', e?.message || 'Unknown error');
    }
    setAddingSample(false);
  };

  const handleSaveMeta = async () => {
    if (!selected) return;
    let inSchema: any = null;
    let outSchema: any = null;
    if (editInputSchema.trim()) {
      try { inSchema = JSON.parse(editInputSchema); }
      catch (e: any) { setEditError(`Inputs is not valid JSON: ${e.message}`); return; }
    }
    if (editOutputSchema.trim()) {
      try { outSchema = JSON.parse(editOutputSchema); }
      catch (e: any) { setEditError(`Outputs is not valid JSON: ${e.message}`); return; }
    }
    setEditError('');
    setBusy('save');
    try {
      await apiFetch<MLModel>(`/api/ml-models/${selected.id}`, {
        method: 'PUT',
        body: JSON.stringify({ description: editDesc, input_schema: inSchema, output_schema: outSchema }),
      });
      await refresh();
      toastSuccess('Saved', 'Model details updated');
      setEditing(false);
    } catch (e: any) {
      setEditError(e?.message || 'Save failed');
      toastError('Save failed', e?.message || 'Unknown error');
    }
    setBusy(null);
  };

  // every action refetches the list and the detail panel derives from it
  const runAction = async (key: string, fn: () => Promise<unknown>, ok: [string, string?], fail: string) => {
    setBusy(key);
    try {
      await fn();
      await refresh();
      toastSuccess(ok[0], ok[1]);
    } catch (e: any) {
      await refresh();
      toastError(fail, e?.message || 'Unknown error');
    }
    setBusy(null);
  };

  const handleDeploy = (m: MLModel) => runAction(
    'deploy',
    async () => {
      const body: Record<string, unknown> = { deployment_type: deployType, replicas: deployType === 'k8s' ? deployReplicas : 1 };
      if (deployType === 'k8s') body.resource_preset = deployPreset;
      await apiFetch(`/api/ml-models/${m.id}/deploy`, { method: 'POST', body: JSON.stringify(body) });
    },
    deployType === 'k8s'
      ? ['Deployment started', `Starting ${deployReplicas} pod(s). The status updates here when they are ready.`]
      : ['Deployed', 'Served in-process by the API and agent runtime'],
    'Deploy failed',
  );

  const handleUndeploy = (m: MLModel) => runAction(
    'undeploy',
    () => apiFetch(`/api/ml-models/${m.id}/undeploy`, { method: 'DELETE' }),
    ['Undeployed', 'Predictions and agents keep working in-process'],
    'Undeploy failed',
  );

  const handleActivate = (m: MLModel) => runAction(
    'activate',
    () => apiFetch(`/api/ml-models/${m.id}/activate`, { method: 'POST', body: '{}' }),
    ['Set active', `Agents calling "${m.name}" now use v${m.version}`],
    'Activate failed',
  );

  const handleDeactivate = (m: MLModel) => runAction(
    'deactivate',
    () => apiFetch(`/api/ml-models/${m.id}/deactivate`, { method: 'POST', body: '{}' }),
    ['Deactivated', `Agents calling "${m.name}" fall back to the newest ready version`],
    'Deactivate failed',
  );

  const handleDelete = async (m: MLModel) => {
    setBusy('delete');
    try {
      await apiFetch(`/api/ml-models/${m.id}`, { method: 'DELETE' });
      setConfirmDelete(false);
      setSelectedId(null);
      await refresh();
      toastSuccess('Version deleted', `${m.name} v${m.version}`);
    } catch (e: any) {
      toastError('Delete failed', e?.message || 'Unknown error');
    }
    setBusy(null);
  };

  const handlePredict = async (m: MLModel) => {
    let input: any;
    try { input = JSON.parse(predInput); }
    catch (e: any) { setPredOutcome({ ok: false, message: `The input is not valid JSON: ${e.message}` }); return; }
    setPredicting(true);
    setPredOutcome(null);
    try {
      const res = await apiFetch<any>(`/api/ml-models/${m.id}/predict`, {
        method: 'POST',
        body: JSON.stringify({ input_data: input }),
        silent: true,
      });
      setPredOutcome({ ok: true, data: res.data });
    } catch (e: any) {
      setPredOutcome({ ok: false, message: e?.message || 'Prediction failed' });
    }
    setPredicting(false);
    setInvocationsKey(k => k + 1);
  };

  const handleUseInAgent = (m: MLModel) => {
    router.push(`/builder?tool=ml_model&model_name=${encodeURIComponent(m.name)}`);
  };

  const list = models || [];
  const isReady = selected?.status === 'ready';
  const activeDeps = (selected?.deployments || []).filter(d => d.status !== 'stopped');
  const stoppedCount = (selected?.deployments || []).length - activeDeps.length;
  const sameTargetLive = activeDeps.some(d => d.deployment_type === deployType && (d.status === 'running' || d.status === 'deploying'));
  const names = featureNames(selected);
  const nFeatures = featureCount(selected);
  const activeSibling = selected ? list.find(m => m.name === selected.name && m.is_active && m.id !== selected.id) : undefined;

  return (
    <div className="min-h-screen bg-[#0B0F19] p-4 sm:p-6">
      <div className="max-w-7xl mx-auto space-y-4 sm:space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-purple-500/20 to-cyan-500/20 flex items-center justify-center">
            <Brain className="w-5 h-5 text-purple-400" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              ML Models <Sparkles className="w-4 h-4 text-purple-400" />
            </h1>
            <p className="text-sm text-slate-400">Bring a trained model, test it here, then let your agents call it for predictions.</p>
          </div>
        </div>

        {/* How this works */}
        <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5" data-testid="ml-howto">
          <button onClick={toggleHowto} aria-expanded={howtoOpen}
            className="w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm text-cyan-100">
            <Info className="w-4 h-4 text-cyan-300 shrink-0" />
            <span className="flex-1 font-medium">How this works</span>
            {howtoOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
          {howtoOpen && (
            <div className="px-4 pb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs text-slate-300">
              <div className="space-y-1">
                <p className="font-medium text-white">1. Upload a trained model</p>
                <p>scikit-learn or XGBoost saved with joblib or pickle (<code className="text-cyan-300">.joblib</code>, <code className="text-cyan-300">.pkl</code>), ONNX (<code className="text-cyan-300">.onnx</code>) or a whole PyTorch model (<code className="text-cyan-300">.pt</code>, <code className="text-cyan-300">.pth</code>). Abenix loads it right away and tells you if the file is not usable. TensorFlow models need converting to ONNX first.</p>
              </div>
              <div className="space-y-1">
                <p className="font-medium text-white">2. Describe its inputs</p>
                <p>List the feature names in the order the model expects and give an example row. Agents and the test form use this to send the right values. Abenix fills in what it can read from the file.</p>
              </div>
              <div className="space-y-1">
                <p className="font-medium text-white">3. Test it</p>
                <p>Run a prediction on this page. It works as soon as the model is <strong>Ready</strong>, no deploy needed. Every call is counted under Invocations.</p>
              </div>
              <div className="space-y-1">
                <p className="font-medium text-white">4. Use it in an agent</p>
                <p><strong>Use in Agent</strong> opens the Agent Builder with the ML Model tool pointed at this model. Agents call it by name and get the <strong>active</strong> version.</p>
              </div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 sm:gap-6">
          {/* Left: Upload + List */}
          <div className="lg:col-span-4 space-y-4 min-w-0">
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Upload className="w-3.5 h-3.5 text-purple-400" /> Upload a model
              </h3>
              <div className="space-y-2.5">
                <div>
                  <input ref={fileRef} type="file" accept={RUNNABLE_EXTENSIONS.join(',')}
                    onChange={e => onPickFile(e.target.files?.[0] || null)} className="hidden" data-testid="ml-file-input" />
                  <button onClick={() => fileRef.current?.click()}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900/50 border border-dashed border-slate-600 text-xs text-slate-300 hover:text-white hover:border-purple-500 transition-colors text-left truncate">
                    {uploadFile ? `📎 ${uploadFile.name} (${fmtBytes(uploadFile.size)})` : '📎 Choose model file (.joblib, .pkl, .onnx, .pt, .pth)'}
                  </button>
                  {fileHint && (
                    <p className="mt-1 text-[11px] text-amber-300 flex items-start gap-1"><AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /><span>{fileHint}</span></p>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <div className="col-span-2">
                    <label htmlFor="ml-name" className="text-[10px] text-slate-400 mb-1 block">Name <span className="text-red-300">*</span></label>
                    <input id="ml-name" type="text" value={uploadName} onChange={e => { setUploadName(e.target.value); setUploadError(''); setSuggestedVersion(''); }}
                      placeholder="Model name (e.g. iris-classifier)" maxLength={255} className={inputCls} />
                  </div>
                  <div>
                    <label htmlFor="ml-version" className="text-[10px] text-slate-400 mb-1 block">Version</label>
                    <input id="ml-version" type="text" value={uploadVersion} onChange={e => { setUploadVersion(e.target.value); setUploadError(''); setSuggestedVersion(''); }}
                      placeholder={versionPlaceholder} maxLength={50} className={inputCls} data-testid="ml-version-input" />
                  </div>
                </div>
                <p className="text-[10px] text-slate-500 -mt-1">Agents find the model by name. Leave version blank to use v{versionPlaceholder}.</p>
                <div>
                  <label htmlFor="ml-desc" className="text-[10px] text-slate-400 mb-1 block">What it predicts (optional)</label>
                  <input id="ml-desc" type="text" value={uploadDesc} onChange={e => setUploadDesc(e.target.value)}
                    placeholder="e.g. Chance a customer cancels in the next 90 days" className={inputCls} />
                </div>
                <details className="rounded-lg border border-slate-700/50 bg-slate-900/30">
                  <summary className="cursor-pointer px-2.5 py-1.5 text-[11px] text-slate-300 hover:text-white select-none">
                    Inputs and outputs (optional, recommended)
                  </summary>
                  <div className="p-2.5 space-y-2 border-t border-slate-700/50">
                    <p className="text-[10px] text-slate-400 leading-snug">
                      Name the features in the order the model expects and give one example row. Leave blank and Abenix reads the feature count from the file when it can.
                    </p>
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label htmlFor="ml-in-schema" className="text-[10px] text-slate-400">Inputs (JSON)</label>
                        <button type="button" onClick={() => setUploadInputSchema(INPUT_SCHEMA_TEMPLATE)} className="text-[10px] text-cyan-300 hover:text-cyan-200">Insert template</button>
                      </div>
                      <textarea id="ml-in-schema" value={uploadInputSchema} onChange={e => { setUploadInputSchema(e.target.value); setUploadError(''); }}
                        rows={4} placeholder='{"features": ["age","income","tenure"], "example": [35, 50000, 24]}'
                        className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-white font-mono placeholder-slate-600 focus:border-purple-500 focus:outline-none resize-y" />
                    </div>
                    <div>
                      <label htmlFor="ml-out-schema" className="text-[10px] text-slate-400 mb-1 block">Outputs (JSON)</label>
                      <textarea id="ml-out-schema" value={uploadOutputSchema} onChange={e => { setUploadOutputSchema(e.target.value); setUploadError(''); }}
                        rows={3} placeholder='{"type": "classification", "classes": ["stays", "churns"]}'
                        className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-white font-mono placeholder-slate-600 focus:border-purple-500 focus:outline-none resize-y" />
                    </div>
                  </div>
                </details>
                {uploadError && (
                  <div role="alert" className="rounded-lg bg-red-500/10 border border-red-500/30 px-2.5 py-2 text-[11px] text-red-300 flex items-start gap-1.5" data-testid="ml-upload-error">
                    <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <div className="min-w-0 break-words space-y-1.5">
                      <p>{uploadError}</p>
                      {suggestedVersion && (
                        <button onClick={() => { setUploadVersion(suggestedVersion); setUploadError(''); setSuggestedVersion(''); }}
                          className="px-2 py-1 rounded bg-red-500/10 border border-red-500/30 text-red-200 hover:bg-red-500/20">
                          Use version {suggestedVersion}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                <button onClick={handleUpload} disabled={uploading || !uploadFile || !uploadName.trim() || !!fileHint}
                  className="w-full px-3 py-2 rounded-lg bg-gradient-to-r from-purple-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 hover:shadow-lg hover:shadow-purple-500/20 transition-all"
                  data-testid="ml-upload-submit">
                  {uploading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading and checking the file...</> : <><Upload className="w-3.5 h-3.5" /> Upload &amp; Validate</>}
                </button>
                {(!uploadFile || !uploadName.trim()) && !uploading && (
                  <p className="text-[10px] text-slate-500 text-center">{!uploadFile ? 'Choose a model file to continue.' : 'Give the model a name to continue.'}</p>
                )}
                <div className="pt-2 border-t border-slate-700/40">
                  <button onClick={handleTrySample} disabled={addingSample}
                    className="w-full px-3 py-2 rounded-lg bg-slate-900/40 border border-slate-700 text-xs text-slate-300 hover:text-white hover:border-cyan-500/50 flex items-center justify-center gap-2 disabled:opacity-50"
                    data-testid="ml-try-sample">
                    {addingSample ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5 text-cyan-300" />}
                    No model handy? Try the sample iris classifier
                  </button>
                </div>
              </div>
            </div>

            {/* Model list */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Database className="w-3.5 h-3.5 text-cyan-400" /> Your models ({list.length})
              </h3>
              <div className="space-y-1 max-h-[50vh] overflow-y-auto">
                {isLoading && !models && (
                  <div className="flex items-center justify-center gap-2 py-6 text-xs text-slate-500"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading models...</div>
                )}
                {listError && !models && (
                  <div className="py-4 text-center text-xs text-red-300 space-y-2">
                    <p>Could not load models: {listError}</p>
                    <button onClick={() => refresh()} className="px-2 py-1 rounded border border-red-500/30 hover:bg-red-500/10">Try again</button>
                  </div>
                )}
                {list.map(m => {
                  const st = STATUS_STYLES[m.status] || STATUS_STYLES.uploaded;
                  const isSel = selected?.id === m.id;
                  return (
                    <button key={m.id} onClick={() => selectModel(m.id)} data-testid="ml-model-row"
                      className={`w-full text-left px-3 py-2.5 rounded-lg text-xs transition-colors ${
                        isSel ? 'bg-purple-500/10 border border-purple-500/30 text-white' : 'border border-transparent text-slate-400 hover:bg-slate-800/50 hover:text-white'
                      }`}>
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="font-medium flex items-center gap-1.5 min-w-0">
                          <span>{FRAMEWORK_ICONS[m.framework] || '📦'}</span>
                          <span className="truncate">{m.name}</span>
                          {m.is_active && m.status === 'ready' && (
                            <span title="Agents calling this name use this version" className="px-1 py-0.5 rounded text-[8px] font-bold bg-emerald-500/20 text-emerald-300 shrink-0">ACTIVE</span>
                          )}
                        </span>
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0 ${st.text} ${st.bg}`}>{st.label}</span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-slate-400">
                        <span>v{m.version}</span><span>·</span>
                        <span>{m.status === 'error' ? 'could not load' : FRAMEWORK_LABELS[m.framework] || m.framework}</span><span>·</span>
                        <span>{fmtBytes(m.file_size_bytes)}</span>
                      </div>
                    </button>
                  );
                })}
                {models && list.length === 0 && (
                  <p className="text-xs text-slate-500 text-center py-6">No models yet. Upload one above or try the sample.</p>
                )}
              </div>
            </div>
          </div>

          {/* Right: Detail + Actions */}
          <div ref={detailRef} className="lg:col-span-8 space-y-4 min-w-0 scroll-mt-4">
            {!selected ? (
              models && list.length === 0 ? (
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 sm:p-10 text-center" data-testid="ml-empty-state">
                  <FlaskConical className="w-12 h-12 text-cyan-400/40 mx-auto mb-3" />
                  <p className="text-sm text-white font-medium">No models yet</p>
                  <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">Start with the sample: a small scikit-learn classifier that names an iris flower from four measurements. It is ready to test in one click.</p>
                  <button onClick={handleTrySample} disabled={addingSample}
                    className="mt-4 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-xs font-semibold inline-flex items-center gap-2 disabled:opacity-50">
                    {addingSample ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FlaskConical className="w-3.5 h-3.5" />} Try with a sample model
                  </button>
                  <p className="text-[11px] text-slate-500 mt-3">Or upload your own trained model on the left.</p>
                </div>
              ) : (
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-8 sm:p-12 text-center">
                  <Brain className="w-12 h-12 text-purple-400/30 mx-auto mb-3" />
                  <p className="text-sm text-slate-300">Pick a model to test it, use it in an agent, or deploy it</p>
                  <p className="text-xs text-slate-500 mt-1">Or upload a new one on the left</p>
                </div>
              )
            ) : (
              <>
                {/* Model header */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-5" data-testid="ml-detail">
                  <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-3">
                    <div className="min-w-0">
                      <h2 className="text-lg font-bold text-white flex items-center gap-2 flex-wrap">
                        <span>{FRAMEWORK_ICONS[selected.framework] || '📦'}</span>
                        <span className="break-all">{selected.name}</span>
                        <span className="text-xs text-slate-500 font-normal">v{selected.version}</span>
                        {selected.is_active && isReady && <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300">ACTIVE</span>}
                      </h2>
                      {selected.description && <p className="text-xs text-slate-400 mt-1">{selected.description}</p>}
                      {isReady && (
                        <p className="text-[11px] text-slate-500 mt-1" data-testid="ml-active-note">
                          {selected.is_active
                            ? `Agents that call "${selected.name}" use this version.`
                            : activeSibling
                              ? `Inactive. Agents that call "${selected.name}" use v${activeSibling.version}.`
                              : `Inactive. No version of "${selected.name}" is active, so agents use the newest ready one.`}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap sm:justify-end">
                      {isReady && (
                        <button onClick={() => handleUseInAgent(selected)} title="Opens the Agent Builder with the ML Model tool set to this model"
                          className="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs hover:bg-cyan-500/20 transition-colors flex items-center gap-1"
                          data-testid="ml-use-in-agent">
                          <Workflow className="w-3 h-3" /> Use in Agent <ArrowRight className="w-3 h-3" />
                        </button>
                      )}
                      <button onClick={() => setEditing(v => !v)} className={btnGhost} data-testid="ml-edit-metadata">
                        <Pencil className="w-3 h-3" /> {editing ? 'Cancel edit' : 'Edit details'}
                      </button>
                      <button onClick={() => setShowShare(true)} className={btnGhost} data-testid="ml-share">
                        <Share2 className="w-3 h-3" /> Share
                      </button>
                      {isReady && (selected.is_active ? (
                        <button onClick={() => handleDeactivate(selected)} disabled={!!busy} data-testid="ml-deactivate"
                          className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs hover:bg-amber-500/20 transition-colors flex items-center gap-1 disabled:opacity-50">
                          {busy === 'deactivate' && <Loader2 className="w-3 h-3 animate-spin" />} Deactivate
                        </button>
                      ) : (
                        <button onClick={() => handleActivate(selected)} disabled={!!busy} data-testid="ml-activate"
                          className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs hover:bg-emerald-500/20 transition-colors flex items-center gap-1 disabled:opacity-50">
                          {busy === 'activate' ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />} Set Active
                        </button>
                      ))}
                      <button onClick={() => setConfirmDelete(true)} disabled={!!busy}
                        className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs hover:bg-red-500/20 transition-colors flex items-center gap-1 disabled:opacity-50">
                        <Trash2 className="w-3 h-3" /> Delete Version
                      </button>
                    </div>
                  </div>

                  {selected.status === 'error' && (
                    <div role="alert" className="mb-3 rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-200 flex items-start gap-2" data-testid="ml-error-reason">
                      <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-300" />
                      <div className="min-w-0 break-words space-y-1">
                        <p className="font-semibold text-red-100">This model could not be loaded, so it cannot be tested, deployed or used by agents.</p>
                        <p>{selected.status_message || 'The file failed validation.'}</p>
                        <p className="text-red-300/80">Upload a fixed file under the same name to add a new version, then delete this one.</p>
                      </div>
                    </div>
                  )}

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Framework</p>
                      <p className="text-sm text-white font-medium">{FRAMEWORK_LABELS[selected.framework] || selected.framework}</p>
                      {selected.status === 'error' && <p className="text-[9px] text-slate-500">guessed from file type</p>}
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Status</p>
                      <p className={`text-sm font-medium ${(STATUS_STYLES[selected.status] || STATUS_STYLES.uploaded).text}`} data-testid="ml-status">
                        {(STATUS_STYLES[selected.status] || STATUS_STYLES.uploaded).label}
                      </p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Size</p>
                      <p className="text-sm text-white font-medium">{fmtBytes(selected.file_size_bytes)}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Inputs</p>
                      <p className="text-sm text-white font-medium">{nFeatures != null ? `${nFeatures} feature${nFeatures === 1 ? '' : 's'}` : 'Not described'}</p>
                    </div>
                  </div>
                  {isReady && selected.training_metrics && (
                    <details className="mt-3 rounded-lg bg-slate-900/50">
                      <summary className="cursor-pointer px-3 py-2 text-[11px] text-slate-400 hover:text-white select-none">What Abenix read from the file</summary>
                      <pre className="px-3 pb-3 text-[11px] text-slate-300 font-mono whitespace-pre-wrap break-all">{JSON.stringify(selected.training_metrics, null, 2)}</pre>
                    </details>
                  )}
                </div>

                {editing && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-5 space-y-3" data-testid="ml-edit-panel">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                      <Pencil className="w-3.5 h-3.5 text-cyan-400" /> Edit details
                    </h3>
                    <div>
                      <label htmlFor="ml-edit-desc" className="text-[10px] text-slate-400 mb-1 block">What it predicts</label>
                      <textarea id="ml-edit-desc" value={editDesc} onChange={e => setEditDesc(e.target.value)} rows={2}
                        className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-xs text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none resize-y" />
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label htmlFor="ml-edit-in" className="text-[10px] text-slate-400">Inputs (JSON)</label>
                          {!editInputSchema.trim() && (
                            <button type="button" onClick={() => setEditInputSchema(INPUT_SCHEMA_TEMPLATE)} className="text-[10px] text-cyan-300 hover:text-cyan-200">Insert template</button>
                          )}
                        </div>
                        <textarea id="ml-edit-in" value={editInputSchema} onChange={e => { setEditInputSchema(e.target.value); setEditError(''); }} rows={6}
                          className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-white font-mono focus:border-cyan-500 focus:outline-none resize-y" />
                        <p className="text-[10px] text-slate-500 mt-1">Use <code>features</code> for names in order and <code>example</code> for one row. The test form starts from the example.</p>
                      </div>
                      <div>
                        <label htmlFor="ml-edit-out" className="text-[10px] text-slate-400 mb-1 block">Outputs (JSON)</label>
                        <textarea id="ml-edit-out" value={editOutputSchema} onChange={e => { setEditOutputSchema(e.target.value); setEditError(''); }} rows={6}
                          className="w-full bg-slate-900/50 border border-slate-700 rounded px-2 py-1.5 text-[11px] text-white font-mono focus:border-cyan-500 focus:outline-none resize-y" />
                      </div>
                    </div>
                    {editError && (
                      <p role="alert" className="text-[11px] text-red-300 flex items-start gap-1"><AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /><span>{editError}</span></p>
                    )}
                    <button onClick={handleSaveMeta} disabled={busy === 'save'}
                      className="px-4 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 hover:bg-cyan-500/20 transition-colors"
                      data-testid="ml-save-metadata">
                      {busy === 'save' ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</> : <>Save details</>}
                    </button>
                  </div>
                )}

                {isReady && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-5" data-testid="ml-test-panel">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-1 flex items-center gap-2">
                      <Play className="w-3.5 h-3.5 text-emerald-400" /> Test inference
                    </h3>
                    <p className="text-[11px] text-slate-400 mb-3">Send one row of feature values as <code className="text-slate-300">{'{"features": [...]}'}</code>, or several rows as a list of lists. Works right now, no deploy needed.</p>
                    {names.length > 0 ? (
                      <div className="mb-2 flex flex-wrap items-center gap-1">
                        <span className="text-[10px] text-slate-400 mr-1">In this order ({names.length}):</span>
                        {names.map((f, i) => (
                          <span key={`${f}-${i}`} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-300 border border-slate-700/50">{f}</span>
                        ))}
                      </div>
                    ) : nFeatures != null ? (
                      <p className="mb-2 text-[10px] text-slate-400">This model takes {nFeatures} numeric value{nFeatures === 1 ? '' : 's'} per row. Add feature names under Edit details to make this clearer for agents.</p>
                    ) : (
                      <p className="mb-2 text-[10px] text-amber-300">The inputs are not described. Add them under Edit details so agents know what to send.</p>
                    )}
                    <textarea value={predInput} onChange={e => setPredInput(e.target.value)} rows={3} aria-label="Prediction input JSON"
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono placeholder-slate-500 focus:border-emerald-500 focus:outline-none resize-y mb-2"
                      data-testid="ml-predict-input" />
                    <div className="flex items-center gap-2 flex-wrap">
                      <button onClick={() => handlePredict(selected)} disabled={predicting || !predInput.trim()}
                        className="px-4 py-2 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 hover:bg-emerald-500/20 transition-colors"
                        data-testid="ml-predict">
                        {predicting ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Predicting...</> : <><Play className="w-3.5 h-3.5" /> Run Prediction</>}
                      </button>
                      <button onClick={() => { setPredInput(defaultInputFor(selected)); setPredOutcome(null); }} className={btnGhost}>
                        <RotateCcw className="w-3 h-3" /> Reset to example
                      </button>
                    </div>
                    {predOutcome?.ok === false && (
                      <div role="alert" className="mt-3 rounded-lg bg-red-500/10 border border-red-500/30 p-3 text-xs text-red-200 flex items-start gap-2" data-testid="ml-predict-error">
                        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-300" />
                        <span className="min-w-0 break-words">{predOutcome.message}</span>
                      </div>
                    )}
                    {predOutcome?.ok && (
                      <div className="mt-3 space-y-2" data-testid="ml-predict-result">
                        <p className="text-xs text-emerald-200 flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          {predOutcome.data?.predicted_class != null
                            ? <>Predicted <strong className="text-white">{String(predOutcome.data.predicted_class)}</strong>
                                {Array.isArray(predOutcome.data?.probabilities?.[0]) && (
                                  <> ({Math.round(Math.max(...predOutcome.data.probabilities[0]) * 100)}% confidence)</>
                                )}</>
                            : <>Prediction returned</>}
                          {predOutcome.data?.latency_ms != null && <span className="text-slate-500">· {predOutcome.data.latency_ms} ms</span>}
                        </p>
                        <pre className="rounded-lg bg-slate-900/80 border border-slate-700/50 p-3 text-[11px] text-slate-300 font-mono whitespace-pre-wrap break-all max-h-48 overflow-y-auto">{JSON.stringify(predOutcome.data, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                )}

                {isReady && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-5">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-1 flex items-center gap-2">
                      <Workflow className="w-3.5 h-3.5 text-cyan-400" /> Use it in an agent
                    </h3>
                    <p className="text-[11px] text-slate-400 mb-3">Agents call models through the ML Model tool by name. <strong className="text-slate-300">Use in Agent</strong> opens the Agent Builder with that tool added and set to <code className="text-cyan-300">{selected.name}</code>. Save the agent, then ask it for a prediction.</p>
                    <button onClick={() => handleUseInAgent(selected)}
                      className="px-4 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-semibold hover:bg-cyan-500/20 transition-colors inline-flex items-center gap-2">
                      Open in the Agent Builder <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}

                {isReady && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-5" data-testid="ml-deploy-panel">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-1 flex items-center gap-2">
                      <Server className="w-3.5 h-3.5 text-cyan-400" /> Deploy (optional)
                    </h3>
                    <p className="text-[11px] text-slate-400 mb-3">You can test predictions right away and agents can already use this model. Deploy runs the model as its own service for production traffic.</p>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                      <button onClick={() => setDeployType('local')} aria-pressed={deployType === 'local'}
                        className={`px-3 py-2 rounded-lg text-xs text-left transition-colors ${deployType === 'local' ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300' : 'bg-slate-900/30 border border-slate-700 text-slate-400'}`}
                        data-testid="deploy-type-local">
                        <span className="flex items-center gap-2 font-medium"><Monitor className="w-3.5 h-3.5" /> Local (in-process)</span>
                        <span className="block text-[10px] text-slate-500 mt-0.5">Marks the model as served by the API and agent runtime. Nothing new starts.</span>
                      </button>
                      <button onClick={() => setDeployType('k8s')} aria-pressed={deployType === 'k8s'}
                        className={`px-3 py-2 rounded-lg text-xs text-left transition-colors ${deployType === 'k8s' ? 'bg-blue-500/10 border border-blue-500/30 text-blue-300' : 'bg-slate-900/30 border border-slate-700 text-slate-400'}`}
                        data-testid="deploy-type-k8s">
                        <span className="flex items-center gap-2 font-medium"><Cloud className="w-3.5 h-3.5" /> Kubernetes pods</span>
                        <span className="block text-[10px] text-slate-500 mt-0.5">Starts dedicated pods for heavy traffic. Admins only.</span>
                      </button>
                    </div>
                    {deployType === 'k8s' && (
                      <div className="mb-3 grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg bg-slate-900/40 border border-slate-700/40 p-3" data-testid="k8s-deploy-config">
                        <div>
                          <label htmlFor="ml-replicas" className="text-[10px] text-slate-400 mb-1 block">Replicas</label>
                          <input id="ml-replicas" type="number" min={1} max={10} value={deployReplicas}
                            onChange={e => setDeployReplicas(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
                            className="w-full bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
                            data-testid="deploy-replicas-input" />
                          <p className="text-[10px] text-slate-500 mt-1">1 to 10. Each replica is a separate pod.</p>
                        </div>
                        <div>
                          <label htmlFor="ml-preset" className="text-[10px] text-slate-400 mb-1 block">Size per pod</label>
                          <select id="ml-preset" value={deployPreset}
                            onChange={e => setDeployPreset(e.target.value as 'small' | 'medium' | 'large')}
                            className="w-full bg-slate-900/60 border border-slate-700 rounded px-2 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
                            data-testid="deploy-preset-select">
                            <option value="small">Small: 0.1 CPU, 256 MB (up to 0.5 CPU, 1 GB)</option>
                            <option value="medium">Medium: 0.25 CPU, 512 MB (up to 1 CPU, 2 GB)</option>
                            <option value="large">Large: 0.5 CPU, 1 GB (up to 2 CPU, 4 GB)</option>
                          </select>
                        </div>
                      </div>
                    )}
                    <div className="flex items-center gap-2 flex-wrap">
                      <button onClick={() => handleDeploy(selected)} disabled={!!busy || (deployType === 'local' && sameTargetLive)}
                        className="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 hover:shadow-lg hover:shadow-emerald-500/20 transition-all"
                        data-testid="ml-deploy">
                        {busy === 'deploy'
                          ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Deploying...</>
                          : deployType === 'local' && sameTargetLive
                            ? <><CheckCircle2 className="w-3.5 h-3.5" /> Running locally</>
                            : <><Play className="w-3.5 h-3.5" /> {sameTargetLive ? 'Update deployment' : 'Deploy'}</>}
                      </button>
                      {activeDeps.some(d => d.status === 'running' || d.status === 'deploying') && (
                        <button onClick={() => handleUndeploy(selected)} disabled={!!busy} className={btnGhost} data-testid="ml-undeploy">
                          {busy === 'undeploy' && <Loader2 className="w-3 h-3 animate-spin" />} Undeploy
                        </button>
                      )}
                    </div>
                    {activeDeps.map(d => {
                      const ds = STATUS_STYLES[d.status] || STATUS_STYLES.stopped;
                      return (
                        <div key={d.id} className="mt-2 rounded-lg bg-slate-900/50 p-2 flex items-center gap-2 text-[11px] min-w-0" data-testid="ml-deployment-row">
                          {d.deployment_type === 'k8s' ? <Cloud className="w-3 h-3 text-blue-400 shrink-0" /> : <Monitor className="w-3 h-3 text-emerald-400 shrink-0" />}
                          <span className="text-slate-300">{d.deployment_type === 'k8s' ? 'Kubernetes' : 'Local'}</span>
                          <span className={`px-1 py-0.5 rounded ${ds.text} ${ds.bg}`}>{ds.label}</span>
                          {d.status === 'deploying' && <Loader2 className="w-3 h-3 animate-spin text-cyan-300" />}
                          {d.endpoint_url && <span className="text-slate-500 font-mono truncate">{d.endpoint_url}</span>}
                        </div>
                      );
                    })}
                    {activeDeps.length === 0 && (
                      <p className="mt-2 text-[11px] text-slate-500">Not deployed. Predictions and agents run the model in-process.</p>
                    )}
                    {stoppedCount > 0 && <p className="mt-1 text-[10px] text-slate-600">{stoppedCount} earlier deployment{stoppedCount === 1 ? '' : 's'} stopped.</p>}
                  </div>
                )}

                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-5">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-1 flex items-center gap-2">
                    <Cpu className="w-3.5 h-3.5 text-cyan-400" /> Invocations
                  </h3>
                  <p className="text-[11px] text-slate-400 mb-3">Every prediction from this page, the API and agents, including failed ones.</p>
                  <InvocationsTable key={`${selected.id}-${invocationsKey}`} kind="ml_model" resourceId={selected.id} />
                </div>

                {(selected.input_schema || selected.output_schema) && (
                  <details className="bg-slate-800/30 border border-slate-700/50 rounded-xl">
                    <summary className="cursor-pointer px-4 sm:px-5 py-3 text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2 select-none">
                      <FileCode2 className="w-3.5 h-3.5 text-purple-400" /> Input and output description (JSON)
                    </summary>
                    <div className="px-4 sm:px-5 pb-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                      {selected.input_schema && (
                        <div className="min-w-0">
                          <p className="text-[10px] text-slate-500 uppercase mb-1">Input</p>
                          <pre className="rounded-lg bg-slate-900/80 p-2 text-[10px] text-slate-300 font-mono whitespace-pre-wrap break-all">{JSON.stringify(selected.input_schema, null, 2)}</pre>
                        </div>
                      )}
                      {selected.output_schema && (
                        <div className="min-w-0">
                          <p className="text-[10px] text-slate-500 uppercase mb-1">Output</p>
                          <pre className="rounded-lg bg-slate-900/80 p-2 text-[10px] text-slate-300 font-mono whitespace-pre-wrap break-all">{JSON.stringify(selected.output_schema, null, 2)}</pre>
                        </div>
                      )}
                    </div>
                  </details>
                )}
              </>
            )}
          </div>
        </div>
      </div>
      {selected && (
        <>
          <ResourceShareDialog
            open={showShare}
            onClose={() => setShowShare(false)}
            resourceType="ml_model"
            resourceId={selected.id}
            resourceName={`${selected.name} v${selected.version}`}
          />
          <ConfirmModal
            open={confirmDelete}
            onClose={() => setConfirmDelete(false)}
            onConfirm={() => handleDelete(selected)}
            title={`Delete ${selected.name} v${selected.version}?`}
            description={selected.is_active && selected.status === 'ready'
              ? `This is the active version. Agents that call "${selected.name}" will use another ready version if one exists, otherwise their calls fail. The file is removed and this cannot be undone.`
              : 'The file is removed and this cannot be undone.'}
            confirmLabel="Delete version"
            loading={busy === 'delete'}
          />
        </>
      )}
    </div>
  );
}
