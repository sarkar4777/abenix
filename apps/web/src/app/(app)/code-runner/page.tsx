'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Box, Check, ChevronRight, CircleAlert, Code2, Download, FileArchive,
  FlaskConical, Github, Loader2, Play, Trash2, Upload, Workflow, ArrowRight,
  Share2,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';
import ResourceShareDialog from '@/components/share/ResourceShareDialog';
import InvocationsTable from '@/components/observability/InvocationsTable';
import OwnerBadge from '@/components/OwnerBadge';
import DeleteWithDependents from '@/components/ui/DeleteWithDependents';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';

interface AnalysisNote {
  level: 'info' | 'warn' | 'error';
  message: string;
  suggestion?: string;
}

interface CodeAsset {
  id: string;
  name: string;
  description: string | null;
  source_type: 'zip' | 'git';
  source_git_url: string | null;
  source_ref: string | null;
  file_size_bytes: number | null;
  detected_language: string | null;
  detected_version: string | null;
  detected_package_manager: string | null;
  detected_entrypoint: string | null;
  suggested_image: string | null;
  suggested_build_command: string | null;
  suggested_run_command: string | null;
  analysis_notes: AnalysisNote[];
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  status: 'uploaded' | 'analyzing' | 'ready' | 'failed' | 'deleted';
  error: string | null;
  last_test_input: unknown;
  last_test_output: unknown;
  last_test_ok: boolean | null;
  last_test_at: string | null;
  owner_name?: string | null;
  ownership?: 'mine' | 'shared' | 'platform' | null;
  can_manage?: boolean;
  version?: number;
  version_history?: { version: number; replaced_at?: string; detected_entrypoint?: string | null; file_size_bytes?: number | null; source_type?: string }[];
  created_at: string;
}

const STATUS_COLORS: Record<string, string> = {
  uploaded:  'bg-amber-500/10 text-amber-300 border-amber-500/30',
  analyzing: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
  ready:     'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  failed:    'bg-red-500/10 text-red-300 border-red-500/30',
};
const LANG_ICON: Record<string, string> = {
  python: '🐍', node: '🟢', go: '🐹', rust: '🦀', ruby: '💎', java: '☕',
};

function fmtBytes(b: number | null): string {
  if (!b) return '—';
  if (b >= 1e6) return `${(b / 1e6).toFixed(1)} MB`;
  if (b >= 1e3) return `${(b / 1e3).toFixed(0)} KB`;
  return `${b} B`;
}

const PENDING_STATUSES = ['uploaded', 'analyzing', 'pending', 'building'];

export default function CodeRunnerPage() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  // poll while an upload is still being analysed, otherwise the badge never moves
  const { data: assets, mutate } = useApi<CodeAsset[]>('/api/code-assets', pending ? { refreshInterval: 3000 } : undefined);
  const [selected, setSelected] = useState<CodeAsset | null>(null);
  // the asset we just created, until analysis ends
  const [watchId, setWatchId] = useState<string | null>(null);
  const [readyAsset, setReadyAsset] = useState<CodeAsset | null>(null);
  useEffect(() => {
    setPending((assets || []).some(a => PENDING_STATUSES.includes(a.status)));
    if (watchId) {
      const w = (assets || []).find(a => a.id === watchId);
      if (w && w.status === 'ready') { setReadyAsset(w); setWatchId(null); }
      else if (w && w.status === 'failed') setWatchId(null);
    }
    // the open asset follows the list, so Run enables when analysis finishes
    setSelected(sel => {
      if (!sel) return sel;
      const fresh = (assets || []).find(a => a.id === sel.id);
      return fresh && fresh.status !== sel.status ? { ...sel, ...fresh } : sel;
    });
  }, [assets, watchId]);

  // Inline JSON lint state for the schema textareas — replaces the
  // alert() blocker so users see the error next to the field.
  const [inputSchemaError, setInputSchemaError] = useState('');
  const [outputSchemaError, setOutputSchemaError] = useState('');
  const [testInputError, setTestInputError] = useState('');
  const [savingMeta, setSavingMeta] = useState(false);
  const [showShare, setShowShare] = useState(false);

  // upload form
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newZip, setNewZip] = useState<File | null>(null);
  const [newGitUrl, setNewGitUrl] = useState('');
  const [newGitRef, setNewGitRef] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const versionFileRef = useRef<HTMLInputElement>(null);
  const [versionBusy, setVersionBusy] = useState(false);
  const [versionError, setVersionError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  // test form
  const [testInput, setTestInput] = useState('{}');
  const [testing, setTesting] = useState(false);
  const [testOutput, setTestOutput] = useState('');
  const [testOk, setTestOk] = useState<boolean | null>(null);

  // schema editors
  const [inputSchemaText, setInputSchemaText] = useState('');
  const [outputSchemaText, setOutputSchemaText] = useState('');

  useEffect(() => {
    if (selected) {
      setInputSchemaText(
        selected.input_schema ? JSON.stringify(selected.input_schema, null, 2) : '',
      );
      setOutputSchemaText(
        selected.output_schema ? JSON.stringify(selected.output_schema, null, 2) : '',
      );
      setTestOutput(
        selected.last_test_output ? JSON.stringify(selected.last_test_output, null, 2) : '',
      );
      setTestOk(selected.last_test_ok);
    }
  }, [selected?.id]);

  const refresh = () => mutate();

  const handleCreate = async () => {
    if (!newName) { setUploadError('Name is required'); return; }
    if (!newZip && !newGitUrl) { setUploadError('Upload a zip or provide a git URL'); return; }
    setUploading(true); setUploadError('');
    try {
      const fd = new FormData();
      if (newZip) fd.append('file', newZip);
      fd.append('metadata', JSON.stringify({
        name: newName, description: newDesc, git_url: newGitUrl, git_ref: newGitRef,
      }));
      const res = await apiFetch<CodeAsset>('/api/code-assets', { method: 'POST', body: fd, headers: {} });
      const created = res?.data;
      if (created?.id) {
        setReadyAsset(null);
        if (created.status === 'ready') setReadyAsset(created);
        else setWatchId(created.id);
      }
      setNewName(''); setNewDesc(''); setNewZip(null); setNewGitUrl(''); setNewGitRef('');
      if (fileRef.current) fileRef.current.value = '';
      toastSuccess('Asset created', `Analyzing ${newName}…`);
      refresh();
    } catch (e: any) {
      const msg = e?.message || 'Upload failed';
      setUploadError(msg);
      toastError('Upload failed', msg);
    }
    setUploading(false);
  };

  const handleNewVersion = async (file: File | undefined) => {
    if (!selected || !file) return;
    setVersionBusy(true); setVersionError('');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('metadata', '{}');
      const res = await apiFetch<CodeAsset>(`/api/code-assets/${selected.id}/versions`, { method: 'POST', body: fd, headers: {} });
      if (res?.data) setSelected(res.data);
      toastSuccess(`Version ${res?.data?.version ?? ''} is live`, 'Agents using this asset run the new code from their next call.');
      refresh();
    } catch (e: any) {
      const msg = e?.message || 'Upload failed';
      setVersionError(msg);
      toastError('New version not applied', msg);
    }
    if (versionFileRef.current) versionFileRef.current.value = '';
    setVersionBusy(false);
  };

  const handleRestore = async (version: number) => {
    if (!selected) return;
    if (!confirm(`Make version ${version} live again? Agents using this asset switch on their next call.`)) return;
    setVersionBusy(true); setVersionError('');
    try {
      const res = await apiFetch<CodeAsset>(`/api/code-assets/${selected.id}/versions/${version}/restore`, { method: 'POST' });
      if (res?.data) setSelected(res.data);
      toastSuccess(`Version ${version} restored`, `Now live as version ${res?.data?.version ?? ''}.`);
      refresh();
    } catch (e: any) {
      setVersionError(e?.message || 'Restore failed');
    }
    setVersionBusy(false);
  };

  const [deletingAsset, setDeletingAsset] = useState<CodeAsset | null>(null);
  const handleDelete = (id: string) => {
    const a = (assets || []).find((x) => x.id === id) || (selected?.id === id ? selected : null);
    if (a) setDeletingAsset(a);
  };
  const doDelete = async (id: string, force: boolean) => {
    try {
      await apiFetch(`/api/code-assets/${id}${force ? '?force=true' : ''}`, { method: 'DELETE' });
      toastSuccess('Asset deleted');
      if (selected?.id === id) setSelected(null);
      refresh();
    } catch (e: any) {
      toastError('Delete failed', e?.message || 'Unknown error');
    }
  };

  const handleSaveMeta = async () => {
    if (!selected) return;
    let inSchema: any = null;
    let outSchema: any = null;
    if (inputSchemaText.trim()) {
      try { inSchema = JSON.parse(inputSchemaText); setInputSchemaError(''); }
      catch (e: any) { setInputSchemaError(`Not valid JSON: ${e.message}`); return; }
    } else setInputSchemaError('');
    if (outputSchemaText.trim()) {
      try { outSchema = JSON.parse(outputSchemaText); setOutputSchemaError(''); }
      catch (e: any) { setOutputSchemaError(`Not valid JSON: ${e.message}`); return; }
    } else setOutputSchemaError('');
    setSavingMeta(true);
    try {
      const r = await apiFetch<CodeAsset>(`/api/code-assets/${selected.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          input_schema: inSchema,
          output_schema: outSchema,
          suggested_image: selected.suggested_image,
          suggested_build_command: selected.suggested_build_command,
          suggested_run_command: selected.suggested_run_command,
        }),
      });
      if (r.data) setSelected(r.data);
      toastSuccess('Saved', 'Schemas + commands updated');
      refresh();
    } catch (e: any) {
      toastError('Save failed', e?.message || 'Unknown error');
    }
    setSavingMeta(false);
  };

  const agentHrefFor = (id: string) => `/builder?tool=code_asset&asset_id=${encodeURIComponent(id)}`;
  const handleUseInAgent = () => {
    if (!selected) return;
    router.push(agentHrefFor(selected.id));
  };

  const goToTest = (a: CodeAsset) => {
    setSelected(a);
    setTimeout(() => {
      const el = document.querySelector('[data-testid="code-test-input"]') as HTMLTextAreaElement | null;
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el?.focus({ preventScroll: true });
    }, 50);
  };

  const handleTest = async () => {
    if (!selected) return;
    let inp: any = {};
    if (testInput.trim()) {
      try { inp = JSON.parse(testInput); setTestInputError(''); }
      catch (e: any) { setTestInputError(`Not valid JSON: ${e.message}`); return; }
    } else setTestInputError('');
    setTesting(true); setTestOutput(''); setTestOk(null);
    try {
      const r = await apiFetch<any>(`/api/code-assets/${selected.id}/test`, {
        method: 'POST',
        body: JSON.stringify({ input: inp, timeout_seconds: 180 }),
      });
      const execution = r.data?.execution;
      setTestOutput(JSON.stringify(execution, null, 2));
      setTestOk(Boolean(execution?.schema_ok ?? true));
      refresh();
    } catch (e: any) {
      setTestOutput(`Error: ${e?.message || String(e)}`);
      setTestOk(false);
    }
    setTesting(false);
  };

  return (
    <div className="min-h-screen bg-[#0B0F19] p-4 sm:p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        <PageHeader
          title="Code Runner"
          purpose="Bring your own code as a zip or git repo and turn it into a tool your agents and pipelines can call. For developers."
          icon={Code2}
          iconClassName="text-indigo-400"
          storageKey="code-runner"
          docSlug="02-runtime/11-sandboxed-code-execution"
          steps={[
            'Give it a name, then upload a zip or paste a git link.',
            'We read the code and suggest the language, image and run command. You can edit them.',
            'Try it with a test input to check the output looks right.',
            'Use in Agent adds it to an agent as a tool. New versions go live without rewiring.',
          ]}
          primaryAction={{ label: 'New code asset', icon: Upload, onClick: () => { nameRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); nameRef.current?.focus({ preventScroll: true }); }, testId: 'code-new-asset' }}
        />

        {readyAsset && (
          <NextSteps
            title={`${readyAsset.name} is ready. What next?`}
            testId="code-next-steps"
            onDismiss={() => setReadyAsset(null)}
            steps={[
              { id: 'test', label: 'Try a test run', hint: 'Send sample input and check the output.', icon: Play, onClick: () => goToTest(readyAsset) },
              { id: 'agent', label: 'Use in an agent', hint: 'Open the builder with this code as a tool.', icon: Workflow, href: agentHrefFor(readyAsset.id) },
            ]}
          />
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: upload + list */}
          <div className="lg:col-span-4 space-y-4 min-w-0">
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Upload className="w-3.5 h-3.5 text-indigo-400" /> New asset
              </h3>
              <div className="space-y-2">
                <input ref={nameRef} type="text" value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder="Name (e.g. sentiment-scorer)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />
                <input type="text" value={newDesc} onChange={e => setNewDesc(e.target.value)}
                  placeholder="Description (optional)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />

                <div className={`flex items-center gap-2 ${newGitUrl ? 'opacity-40 pointer-events-none' : ''}`}>
                  <input ref={fileRef} type="file" accept=".zip"
                    onChange={e => setNewZip(e.target.files?.[0] || null)} className="hidden" />
                  <button onClick={() => fileRef.current?.click()}
                    disabled={!!newGitUrl}
                    className="flex-1 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700 text-xs text-slate-400 hover:text-white hover:border-slate-600 disabled:opacity-50 disabled:cursor-not-allowed text-left truncate flex items-center gap-2"
                    data-testid="code-source-zip"
                    aria-label="Choose a .zip file to upload">
                    <FileArchive className="w-3.5 h-3.5" />
                    {newZip ? newZip.name : 'Choose a .zip file'}
                  </button>
                </div>
                <div className="text-[10px] text-slate-400 text-center select-none">— or —</div>
                <div className={newZip ? 'opacity-40 pointer-events-none space-y-2' : 'space-y-2'}>
                  <input type="text" value={newGitUrl} onChange={e => setNewGitUrl(e.target.value)}
                    placeholder="https://github.com/owner/repo"
                    disabled={!!newZip}
                    className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    data-testid="code-source-git-url" />
                  <input type="text" value={newGitRef} onChange={e => setNewGitRef(e.target.value)}
                    placeholder="branch / tag / commit (optional)"
                    disabled={!!newZip}
                    className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white disabled:opacity-50 disabled:cursor-not-allowed" />
                </div>

                {uploadError && (
                  <p className="text-xs text-red-400 flex items-center gap-1"><CircleAlert className="w-3 h-3" /> {uploadError}</p>
                )}
                <button onClick={handleCreate} disabled={uploading}
                  className="w-full px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-50 flex items-center justify-center gap-2">
                  {uploading ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Analyzing…</> : <>Create & analyze</>}
                </button>
              </div>
            </div>

            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-2 max-h-[500px] overflow-y-auto">
              <div className="space-y-1">
                {(assets || []).length === 0 && (
                  <p className="text-xs text-slate-500 text-center py-6">No code assets yet</p>
                )}
                {(assets || []).map(a => (
                  <button key={a.id} onClick={() => setSelected(a)}
                    data-testid="code-asset-item" data-name={a.name} data-status={a.status}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs ${selected?.id === a.id ? 'bg-indigo-500/10 border border-indigo-500/30' : 'bg-slate-900/30 border border-transparent hover:border-slate-700'}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-white flex items-center gap-1.5">
                        <span>{LANG_ICON[a.detected_language || ''] || '📦'}</span>
                        {a.name}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${STATUS_COLORS[a.status] || ''}`}>{a.status}</span>
                    </div>
                    <div className="text-[10px] text-slate-400 flex items-center gap-2">
                      <span>{a.detected_language || '—'} {a.detected_version || ''}</span>
                      <span>·</span>
                      <span>{fmtBytes(a.file_size_bytes)}</span>
                      <OwnerBadge ownership={a.ownership} ownerName={a.owner_name} className="ml-auto" />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Right: detail */}
          <div className="lg:col-span-8 space-y-4 min-w-0">
            {!selected ? (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-12 text-center">
                <Code2 className="w-12 h-12 text-indigo-400/30 mx-auto mb-3" />
                <p className="text-sm text-slate-400">Pick an asset on the left to see its analysis + test it</p>
              </div>
            ) : (
              <>
                {/* Header */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <h2 className="text-lg font-bold text-white flex items-center gap-2">
                        <span>{LANG_ICON[selected.detected_language || ''] || '📦'}</span>
                        {selected.name}
                        <span className="text-xs text-slate-500 font-normal">{selected.detected_version || ''}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-300 font-normal" data-testid="code-version" data-version={selected.version || 1}>
                          v{selected.version || 1}
                        </span>
                      </h2>
                      {selected.description && <p className="text-xs text-slate-400 mt-1">{selected.description}</p>}
                      {selected.source_git_url && (
                        <p className="text-xs text-slate-500 mt-1 flex items-center gap-1">
                          <Github className="w-3 h-3" /> {selected.source_git_url}{selected.source_ref ? `#${selected.source_ref}` : ''}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <button onClick={handleUseInAgent} disabled={selected.status !== 'ready'}
                        className="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs hover:bg-cyan-500/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1"
                        title={selected.status !== 'ready' ? 'Asset must be ready before wiring into an agent' : 'Open builder with code_asset tool pre-configured'}
                        data-testid="code-use-in-agent">
                        <Workflow className="w-3 h-3" /> Use in Agent <ArrowRight className="w-3 h-3" />
                      </button>
                      {selected.can_manage !== false && (
                        <>
                          <input
                            ref={versionFileRef}
                            type="file"
                            accept=".zip,.tar.gz,.tgz"
                            className="hidden"
                            data-testid="code-version-input"
                            onChange={(e) => handleNewVersion(e.target.files?.[0])}
                          />
                          <button onClick={() => versionFileRef.current?.click()} disabled={versionBusy}
                            className="px-3 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs hover:bg-emerald-500/20 disabled:opacity-50 flex items-center gap-1"
                            title="Replace the code behind this asset. Agents keep using it and pick up the new code."
                            data-testid="code-new-version">
                            {versionBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />} Upload new version
                          </button>
                          <button onClick={() => setShowShare(true)}
                            className="px-3 py-1.5 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-300 text-xs hover:bg-slate-700/50 hover:text-white transition-colors flex items-center gap-1"
                            data-testid="code-share">
                            <Share2 className="w-3 h-3" /> Share
                          </button>
                          <button onClick={() => handleDelete(selected.id)}
                            className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs hover:bg-red-500/20 flex items-center gap-1">
                            <Trash2 className="w-3 h-3" /> Delete
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Language</p>
                      <p className="text-sm text-white">{selected.detected_language || '—'}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Package mgr</p>
                      <p className="text-sm text-white">{selected.detected_package_manager || '—'}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Entrypoint</p>
                      <p className="text-sm text-white truncate">{selected.detected_entrypoint || '—'}</p>
                    </div>
                    <div className="rounded-lg bg-slate-900/50 p-3">
                      <p className="text-[10px] text-slate-500 uppercase">Image</p>
                      <p className="text-sm text-white font-mono truncate">{selected.suggested_image || '—'}</p>
                    </div>
                  </div>
                </div>

                {/* Notes */}
                {selected.status === 'failed' && (
                  <div role="alert" data-testid="code-asset-error" className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-xs text-red-200">
                    <p className="font-semibold text-red-100 mb-1">This asset cannot run yet</p>
                    <p>{selected.error || 'Analysis failed. See the notes below.'}</p>
                    {selected.can_manage !== false && (
                      <p className="mt-2 text-red-300">Fix the code and use Upload new version. Agents bound to this asset keep its id.</p>
                    )}
                  </div>
                )}
                {versionError && (
                  <div role="alert" data-testid="code-version-error" className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-200 flex justify-between gap-3">
                    <span>{versionError}</span>
                    <button onClick={() => setVersionError('')} aria-label="Dismiss" className="text-amber-300 hover:text-white">×</button>
                  </div>
                )}
                {(selected.version_history || []).length > 0 && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4" data-testid="code-version-history">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-2">Earlier versions</h3>
                    <ul className="space-y-1">
                      {[...(selected.version_history || [])].reverse().map((h) => (
                        <li key={`${h.version}-${h.replaced_at}`} className="flex items-center justify-between text-xs text-slate-300">
                          <span>
                            v{h.version} · {h.detected_entrypoint || 'entrypoint unknown'}
                            {h.replaced_at && <span className="text-slate-500"> · replaced {new Date(h.replaced_at).toLocaleString()}</span>}
                          </span>
                          {selected.can_manage !== false && (
                            <button onClick={() => handleRestore(h.version)} disabled={versionBusy}
                              className="text-emerald-300 hover:underline disabled:opacity-50" data-testid={`code-restore-${h.version}`}>
                              Restore
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {(selected.analysis_notes || []).length > 0 && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-2">Analyzer notes</h3>
                    <ul className="space-y-1 text-xs">
                      {selected.analysis_notes.map((n, i) => (
                        <li key={i} className={`flex items-start gap-2 ${n.level === 'error' ? 'text-red-300' : n.level === 'warn' ? 'text-amber-300' : 'text-slate-400'}`}>
                          <ChevronRight className="w-3 h-3 mt-0.5 shrink-0" />
                          <div>
                            <div>{n.message}</div>
                            {n.suggestion && <div className="text-[10px] text-slate-400 mt-0.5">Hint: {n.suggestion}</div>}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Commands */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider">Commands (editable)</h3>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Build</p>
                    <input type="text" value={selected.suggested_build_command || ''}
                      onChange={e => setSelected(s => s ? { ...s, suggested_build_command: e.target.value } : s)}
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono" />
                  </div>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Run</p>
                    <input type="text" value={selected.suggested_run_command || ''}
                      onChange={e => setSelected(s => s ? { ...s, suggested_run_command: e.target.value } : s)}
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono" />
                  </div>
                </div>

                {/* I/O schemas */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                    <Box className="w-3.5 h-3.5 text-cyan-400" /> I/O schemas (JSON Schema, optional)
                  </h3>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Input schema</p>
                    <textarea rows={4} value={inputSchemaText}
                      onChange={e => { setInputSchemaText(e.target.value); setInputSchemaError(''); }}
                      onBlur={e => {
                        const v = e.target.value.trim();
                        if (!v) { setInputSchemaError(''); return; }
                        try { JSON.parse(v); setInputSchemaError(''); }
                        catch (err: any) { setInputSchemaError(`Not valid JSON: ${err.message}`); }
                      }}
                      placeholder='{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}'
                      className={`w-full bg-slate-900/50 border rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none ${inputSchemaError ? 'border-red-500/60' : 'border-slate-700 focus:border-cyan-500'}`} />
                    {inputSchemaError && <p className="text-[10px] text-red-300 mt-1 flex items-start gap-1"><CircleAlert className="w-3 h-3 mt-0.5 shrink-0" /><span>{inputSchemaError}</span></p>}
                  </div>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Output schema</p>
                    <textarea rows={4} value={outputSchemaText}
                      onChange={e => { setOutputSchemaText(e.target.value); setOutputSchemaError(''); }}
                      onBlur={e => {
                        const v = e.target.value.trim();
                        if (!v) { setOutputSchemaError(''); return; }
                        try { JSON.parse(v); setOutputSchemaError(''); }
                        catch (err: any) { setOutputSchemaError(`Not valid JSON: ${err.message}`); }
                      }}
                      placeholder='{"type":"object","properties":{"weather":{"type":"string"}}}'
                      className={`w-full bg-slate-900/50 border rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none ${outputSchemaError ? 'border-red-500/60' : 'border-slate-700 focus:border-cyan-500'}`} />
                    {outputSchemaError && <p className="text-[10px] text-red-300 mt-1 flex items-start gap-1"><CircleAlert className="w-3 h-3 mt-0.5 shrink-0" /><span>{outputSchemaError}</span></p>}
                  </div>
                  <button onClick={handleSaveMeta} disabled={savingMeta}
                    className="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    data-testid="code-save-meta">
                    {savingMeta ? <><Loader2 className="w-3 h-3 animate-spin" /> Saving...</> : <>Save schemas + commands</>}
                  </button>
                </div>

                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                    <FlaskConical className="w-3.5 h-3.5 text-cyan-400" /> Invocations
                  </h3>
                  <InvocationsTable kind="code_asset" resourceId={selected.id} />
                </div>

                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                    <FlaskConical className="w-3.5 h-3.5 text-emerald-400" /> Test run
                  </h3>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Input JSON</p>
                    <textarea rows={3} value={testInput} data-testid="code-test-input"
                      onChange={e => { setTestInput(e.target.value); setTestInputError(''); }}
                      onBlur={e => {
                        const v = e.target.value.trim();
                        if (!v) { setTestInputError(''); return; }
                        try { JSON.parse(v); setTestInputError(''); }
                        catch (err: any) { setTestInputError(`Not valid JSON: ${err.message}`); }
                      }}
                      className={`w-full bg-slate-900/50 border rounded-lg px-3 py-2 text-xs text-white font-mono focus:outline-none ${testInputError ? 'border-red-500/60' : 'border-slate-700 focus:border-cyan-500'}`} />
                    {testInputError && <p className="text-[10px] text-red-300 mt-1 flex items-start gap-1"><CircleAlert className="w-3 h-3 mt-0.5 shrink-0" /><span>{testInputError}</span></p>}
                  </div>
                  <button onClick={handleTest} disabled={testing || selected.status !== 'ready'} data-testid="code-test-run"
                    className="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-50 flex items-center gap-2">
                    {testing ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running…</> : <><Play className="w-3.5 h-3.5" /> Run</>}
                  </button>
                  {testOutput && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-1 flex items-center gap-1">
                        Output {testOk === true && <Check className="w-3 h-3 text-emerald-400" />}
                        {testOk === false && <CircleAlert className="w-3 h-3 text-red-400" />}
                      </p>
                      <pre data-testid="code-test-output" className="w-full bg-slate-900/70 border border-slate-700 rounded-lg p-3 text-xs text-slate-300 font-mono overflow-x-auto max-h-64">{testOutput}</pre>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
      {selected && (
        <ResourceShareDialog
          open={showShare}
          onClose={() => setShowShare(false)}
          resourceType="code_asset"
          resourceId={selected.id}
          resourceName={selected.name}
        />
      )}
      <DeleteWithDependents
        open={!!deletingAsset}
        onClose={() => setDeletingAsset(null)}
        resource={`/api/code-assets/${deletingAsset?.id}`}
        name={deletingAsset?.name || ''}
        what="code asset"
        onConfirm={(force) => (deletingAsset ? doDelete(deletingAsset.id, force) : undefined)}
      />
    </div>
  );
}
