'use client';

import { useEffect, useRef, useState } from 'react';
import {
  Box, Check, ChevronRight, CircleAlert, Code2, Download, FileArchive,
  FlaskConical, Github, Loader2, Play, Trash2, Upload,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

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

export default function CodeRunnerPage() {
  const { data: assets, mutate } = useApi<CodeAsset[]>('/api/code-assets');
  const [selected, setSelected] = useState<CodeAsset | null>(null);

  // upload form
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newZip, setNewZip] = useState<File | null>(null);
  const [newGitUrl, setNewGitUrl] = useState('');
  const [newGitRef, setNewGitRef] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

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
      await apiFetch<CodeAsset>('/api/code-assets', { method: 'POST', body: fd, headers: {} });
      setNewName(''); setNewDesc(''); setNewZip(null); setNewGitUrl(''); setNewGitRef('');
      if (fileRef.current) fileRef.current.value = '';
      refresh();
    } catch (e: any) {
      setUploadError(e?.message || 'Upload failed');
    }
    setUploading(false);
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this code asset?')) return;
    await apiFetch(`/api/code-assets/${id}`, { method: 'DELETE' });
    if (selected?.id === id) setSelected(null);
    refresh();
  };

  const handleSaveMeta = async () => {
    if (!selected) return;
    let inSchema: any = null;
    let outSchema: any = null;
    try {
      inSchema = inputSchemaText ? JSON.parse(inputSchemaText) : null;
    } catch { alert('input_schema is not valid JSON'); return; }
    try {
      outSchema = outputSchemaText ? JSON.parse(outputSchemaText) : null;
    } catch { alert('output_schema is not valid JSON'); return; }
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
    refresh();
  };

  const handleTest = async () => {
    if (!selected) return;
    let inp: any = {};
    try { inp = testInput ? JSON.parse(testInput) : {}; }
    catch { alert('input is not valid JSON'); return; }
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
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-cyan-500/20 flex items-center justify-center">
            <Code2 className="w-5 h-5 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">Code Runner</h1>
            <p className="text-sm text-slate-400">Upload a zip or git repo. We analyze, suggest an image + commands, and expose it as a pipeline-callable tool (code_asset).</p>
          </div>
        </div>

        <div className="grid grid-cols-12 gap-6">
          {/* Left: upload + list */}
          <div className="col-span-4 space-y-4">
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-3 flex items-center gap-2">
                <Upload className="w-3.5 h-3.5 text-indigo-400" /> New asset
              </h3>
              <div className="space-y-2">
                <input type="text" value={newName} onChange={e => setNewName(e.target.value)}
                  placeholder="Name (e.g. sentiment-scorer)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />
                <input type="text" value={newDesc} onChange={e => setNewDesc(e.target.value)}
                  placeholder="Description (optional)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />

                <div className="flex items-center gap-2">
                  <input ref={fileRef} type="file" accept=".zip"
                    onChange={e => setNewZip(e.target.files?.[0] || null)} className="hidden" />
                  <button onClick={() => fileRef.current?.click()}
                    className="flex-1 px-3 py-2 rounded-lg bg-slate-900/50 border border-slate-700 text-xs text-slate-400 hover:text-white hover:border-slate-600 text-left truncate flex items-center gap-2">
                    <FileArchive className="w-3.5 h-3.5" />
                    {newZip ? newZip.name : 'Choose a .zip file'}
                  </button>
                </div>
                <div className="text-[10px] text-slate-500 text-center">— or —</div>
                <input type="text" value={newGitUrl} onChange={e => setNewGitUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />
                <input type="text" value={newGitRef} onChange={e => setNewGitRef(e.target.value)}
                  placeholder="branch / tag / commit (optional)"
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white" />

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
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs ${selected?.id === a.id ? 'bg-indigo-500/10 border border-indigo-500/30' : 'bg-slate-900/30 border border-transparent hover:border-slate-700'}`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-white flex items-center gap-1.5">
                        <span>{LANG_ICON[a.detected_language || ''] || '📦'}</span>
                        {a.name}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${STATUS_COLORS[a.status] || ''}`}>{a.status}</span>
                    </div>
                    <div className="text-[10px] text-slate-500 flex gap-2">
                      <span>{a.detected_language || '—'} {a.detected_version || ''}</span>
                      <span>·</span>
                      <span>{fmtBytes(a.file_size_bytes)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Right: detail */}
          <div className="col-span-8 space-y-4">
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
                      </h2>
                      {selected.description && <p className="text-xs text-slate-400 mt-1">{selected.description}</p>}
                      {selected.source_git_url && (
                        <p className="text-xs text-slate-500 mt-1 flex items-center gap-1">
                          <Github className="w-3 h-3" /> {selected.source_git_url}{selected.source_ref ? `#${selected.source_ref}` : ''}
                        </p>
                      )}
                    </div>
                    <button onClick={() => handleDelete(selected.id)}
                      className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs hover:bg-red-500/20 flex items-center gap-1">
                      <Trash2 className="w-3 h-3" /> Delete
                    </button>
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
                {(selected.analysis_notes || []).length > 0 && (
                  <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <h3 className="text-xs font-semibold text-white uppercase tracking-wider mb-2">Analyzer notes</h3>
                    <ul className="space-y-1 text-xs">
                      {selected.analysis_notes.map((n, i) => (
                        <li key={i} className={`flex items-start gap-2 ${n.level === 'error' ? 'text-red-300' : n.level === 'warn' ? 'text-amber-300' : 'text-slate-400'}`}>
                          <ChevronRight className="w-3 h-3 mt-0.5 shrink-0" />
                          <div>
                            <div>{n.message}</div>
                            {n.suggestion && <div className="text-[10px] text-slate-500 mt-0.5">Hint: {n.suggestion}</div>}
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
                      onChange={e => setInputSchemaText(e.target.value)}
                      placeholder='{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}'
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono" />
                  </div>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Output schema</p>
                    <textarea rows={4} value={outputSchemaText}
                      onChange={e => setOutputSchemaText(e.target.value)}
                      placeholder='{"type":"object","properties":{"weather":{"type":"string"}}}'
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono" />
                  </div>
                  <button onClick={handleSaveMeta}
                    className="px-3 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs">
                    Save schemas + commands
                  </button>
                </div>

                {/* Test runner */}
                <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
                  <h3 className="text-xs font-semibold text-white uppercase tracking-wider flex items-center gap-2">
                    <FlaskConical className="w-3.5 h-3.5 text-emerald-400" /> Test run
                  </h3>
                  <div>
                    <p className="text-[10px] text-slate-500 uppercase mb-1">Input JSON</p>
                    <textarea rows={3} value={testInput}
                      onChange={e => setTestInput(e.target.value)}
                      className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono" />
                  </div>
                  <button onClick={handleTest} disabled={testing || selected.status !== 'ready'}
                    className="px-4 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-xs font-semibold disabled:opacity-50 flex items-center gap-2">
                    {testing ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running…</> : <><Play className="w-3.5 h-3.5" /> Run</>}
                  </button>
                  {testOutput && (
                    <div>
                      <p className="text-[10px] text-slate-500 uppercase mb-1 flex items-center gap-1">
                        Output {testOk === true && <Check className="w-3 h-3 text-emerald-400" />}
                        {testOk === false && <CircleAlert className="w-3 h-3 text-red-400" />}
                      </p>
                      <pre className="w-full bg-slate-900/70 border border-slate-700 rounded-lg p-3 text-xs text-slate-300 font-mono overflow-x-auto max-h-64">{testOutput}</pre>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
