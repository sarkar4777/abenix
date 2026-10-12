'use client';

import { useMemo, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Download, FileUp, Loader2, Upload, X } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { Stat } from '@/components/telemetry/bits';
import { API_URL, apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';
import { ACTION_TEXT, LIMITS, csvPrecheck, explainAssetError, importCount, plural, type ImportResult } from './lib';

const SHOW = 200;

async function downloadTemplate() {
  try {
    const token = localStorage.getItem('access_token');
    const res = await fetch(`${API_URL}/api/telemetry/assets/template.csv`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) {
      let message: string | null = null;
      try { const j = await res.json(); message = typeof j?.error === 'string' ? j.error : j?.error?.message ?? null; } catch { /* not JSON */ }
      toastError('Could not download the template', explainAssetError({ status: res.status, message }, 'template'));
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = 'assets-template.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    toastError('Could not download the template', explainAssetError({ status: 0, code: 'NETWORK_ERROR', message: e instanceof Error ? e.message : null }, 'template'));
  }
}

export default function ImportDialog({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileBytes, setFileBytes] = useState<number | undefined>(undefined);
  const [problem, setProblem] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<'check' | 'apply' | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [onlyErrors, setOnlyErrors] = useState(true);
  const [shown, setShown] = useState(SHOW);
  const [confirm, setConfirm] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const reset = () => { setResult(null); setErr(null); setProblem(null); setShown(SHOW); };

  const readFile = (f: File) => {
    reset();
    if (f.size > LIMITS.importBytes) {
      setProblem(`${f.name} is ${(f.size / 1024 / 1024).toFixed(1)} MB. An import takes up to 2 MB, so split it into smaller files.`);
      return;
    }
    const r = new FileReader();
    r.onload = () => { setText(String(r.result || '')); setFileName(f.name); setFileBytes(f.size); };
    r.onerror = () => setProblem('Could not read that file. Try again, or paste the text instead.');
    r.readAsText(f);
  };

  async function send(dryRun: boolean) {
    const pre = csvPrecheck(text, fileBytes);
    setProblem(pre);
    if (pre) return;
    setBusy(dryRun ? 'check' : 'apply');
    setErr(null);
    try {
      const res = await apiFetch<ImportResult>('/api/telemetry/assets/import', { method: 'POST', body: JSON.stringify({ csv: text, dry_run: dryRun }) });
      const data = res.data;
      if (!data || !Array.isArray(data.rows)) { setErr('Abenix sent back an answer this page cannot read. Try again in a moment.'); return; }
      setResult(data);
      setShown(SHOW);
      setOnlyErrors(data.summary.error > 0);
      if (!dryRun) {
        if (data.applied) {
          const n = importCount(data);
          toastSuccess(`${plural(n, 'asset')} imported`, `${plural(data.summary.create, 'new asset')} and ${plural(data.summary.update, 'update')}. Rows that matched were left alone.`);
          onImported();
          onClose();
        } else {
          setErr('Nothing was imported because some rows need fixing. They are marked below. Fix them in the file, then check again.');
        }
      }
    } catch (e) {
      setErr(explainAssetError(e, 'import'));
    } finally {
      setBusy(null);
    }
  }

  const rows = useMemo(() => (result ? (onlyErrors ? result.rows.filter((r) => r.action === 'error') : result.rows) : []), [result, onlyErrors]);
  const n = importCount(result);
  const errors = result?.summary.error ?? 0;
  const canApply = !!result && errors === 0 && n > 0 && !busy;
  const applyTitle = !result ? 'Check the list first' : errors > 0 ? 'Fix the rows that need fixing, then check again' : n === 0 ? 'Every row matches what is saved, so there is nothing to import' : undefined;

  return (
    <>
      <ResponsiveModal open onClose={busy || confirm ? () => {} : onClose} title="Import assets from a CSV" icon={<Upload className="h-4 w-4" />} maxWidth="max-w-3xl">
        <div className="space-y-4" data-testid="assets-import-dialog">
          <p className="text-sm text-slate-300">
            One line per asset or part, with a header row first. Columns are group, node, device, name, type, tags, team, lat, lon, x, y, vin, plate, serial and model. Any other column becomes a field. Leave device empty for the asset itself. Split tags with <code className="rounded bg-slate-800 px-1 text-xs">;</code> or <code className="rounded bg-slate-800 px-1 text-xs">|</code>. Abenix checks every row and shows what would change before anything is saved.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" accept=".csv,text/csv,text/plain" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = ''; }} data-testid="import-file" />
            <button type="button" onClick={() => fileRef.current?.click()} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800" data-testid="import-upload">
              <FileUp className="h-4 w-4" /> {fileName ? 'Pick another file' : 'Upload a file'}
            </button>
            <button type="button" onClick={() => void downloadTemplate()} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-cyan-300 hover:bg-cyan-500/10" data-testid="import-template">
              <Download className="h-4 w-4" /> Download template
            </button>
            {fileName && (
              <span className="inline-flex min-w-0 items-center gap-1 text-xs text-slate-400">
                <span className="truncate">{fileName}</span>
                <button type="button" onClick={() => { setText(''); setFileName(null); setFileBytes(undefined); reset(); }} aria-label="Clear the file" className="rounded p-0.5 hover:text-white"><X className="h-3.5 w-3.5" /></button>
              </span>
            )}
          </div>
          <div>
            <label htmlFor="import-text" className="mb-1 block text-xs font-medium text-slate-300">Or paste the CSV</label>
            <textarea
              id="import-text"
              value={text}
              onChange={(e) => { setText(e.target.value); setFileName(null); setFileBytes(undefined); reset(); }}
              rows={6}
              spellCheck={false}
              placeholder={'group,node,device,name,type,tags\nfleet,truck-42,,Truck 42,vehicle,north;refrigerated'}
              className={`w-full rounded-md border bg-slate-950 px-2.5 py-2 font-mono text-xs text-white placeholder:text-slate-600 ${problem ? 'border-rose-500/60' : 'border-slate-700'}`}
              data-testid="import-text"
            />
            {problem && <p className="mt-1 text-xs text-rose-300" role="alert" data-testid="import-problem">{problem}</p>}
          </div>

          {err && <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert" data-testid="import-error">{err}</p>}

          {result && (
            <div className="space-y-3" data-testid="import-preview">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="import-summary">
                <Stat label="Will add" value={result.summary.create} testId="import-sum-create" />
                <Stat label="Will update" value={result.summary.update} testId="import-sum-update" />
                <Stat label="No change" value={result.summary.unchanged} testId="import-sum-unchanged" />
                <Stat label="Need fixing" value={result.summary.error} tone={errors ? 'bad' : 'plain'} testId="import-sum-error" />
              </div>
              {errors > 0 ? (
                <p className="flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-sm text-rose-100" role="alert">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {plural(errors, 'row needs', 'rows need')} fixing. Nothing is imported until every row is valid. Fix them in the file, then check again.
                </p>
              ) : n > 0 ? (
                <p className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm text-emerald-100" role="status">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> Every row is valid. Nothing is saved until you import.
                </p>
              ) : (
                <p className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300" role="status">Every row matches what is already saved, so there is nothing to import.</p>
              )}
              {errors > 0 && (
                <label className="flex items-center gap-2 text-xs text-slate-300">
                  <input type="checkbox" checked={onlyErrors} onChange={(e) => { setOnlyErrors(e.target.checked); setShown(SHOW); }} className="accent-cyan-500" data-testid="import-only-errors" />
                  Only show rows that need fixing
                </label>
              )}
              <div className="overflow-x-auto rounded-lg border border-slate-700/60">
                <table className="w-full min-w-[32rem] text-left text-xs">
                  <thead className="bg-slate-900/80 text-[11px] uppercase tracking-wide text-slate-500">
                    <tr><th className="px-3 py-2 font-medium">Line</th><th className="px-3 py-2 font-medium">Asset</th><th className="px-3 py-2 font-medium">What happens</th><th className="px-3 py-2 font-medium">Problems</th></tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, shown).map((r) => (
                      <tr key={`${r.line}-${r.key}`} className={`border-t border-slate-800 align-top ${r.action === 'error' ? 'bg-rose-500/10' : ''}`} data-testid="import-row" data-action={r.action}>
                        <td className="px-3 py-2 tabular-nums text-slate-400">{r.line}</td>
                        <td className="px-3 py-2">
                          {r.display_name && <span className="block text-slate-100">{r.display_name}</span>}
                          <span className="block break-all font-mono text-slate-400">{r.key || `${r.group}/${r.node}/${r.device}`}</span>
                        </td>
                        <td className={`whitespace-nowrap px-3 py-2 ${r.action === 'error' ? 'text-rose-200' : r.action === 'unchanged' ? 'text-slate-500' : 'text-emerald-200'}`}>{ACTION_TEXT[r.action] ?? r.action}</td>
                        <td className="px-3 py-2 text-rose-100">{r.errors?.length ? <ul className="space-y-0.5">{r.errors.map((m, i) => <li key={i}>{m}</li>)}</ul> : <span className="text-slate-600">None</span>}</td>
                      </tr>
                    ))}
                    {!rows.length && <tr><td colSpan={4} className="px-3 py-4 text-center text-slate-400">No rows to show.</td></tr>}
                  </tbody>
                </table>
              </div>
              {rows.length > shown && (
                <button type="button" onClick={() => setShown((s) => s + SHOW)} className="text-xs text-cyan-300 hover:underline" data-testid="import-show-more">
                  Show {Math.min(SHOW, rows.length - shown)} more of {rows.length.toLocaleString('en-US')}
                </button>
              )}
            </div>
          )}

          <div className="flex flex-col-reverse gap-2 border-t border-slate-800 pt-3 sm:flex-row sm:items-center">
            <button type="button" onClick={onClose} disabled={!!busy} className="min-h-[40px] rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
            <span className="flex-1" />
            <button type="button" onClick={() => void send(true)} disabled={!!busy || !text.trim()} title={!text.trim() ? 'Upload a file or paste the CSV first' : undefined} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50" data-testid="import-check">
              {busy === 'check' && <Loader2 className="h-4 w-4 animate-spin" />} {result ? 'Check again' : 'Check'}
            </button>
            <button type="button" onClick={() => setConfirm(true)} disabled={!canApply} title={applyTitle} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50" data-testid="import-apply">
              {busy === 'apply' && <Loader2 className="h-4 w-4 animate-spin" />} {n > 0 ? `Import ${plural(n, 'asset')}` : 'Import'}
            </button>
          </div>
        </div>
      </ResponsiveModal>
      <ConfirmModal
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => { setConfirm(false); void send(false); }}
        title={`Import ${plural(n, 'asset')}?`}
        description={`This adds ${plural(result?.summary.create ?? 0, 'new asset')} and updates ${plural(result?.summary.update ?? 0, 'asset')} with the values in the file. Rows marked No change are left alone. Streams keep flowing as they are.`}
        confirmLabel="Import"
        variant="warning"
        confirmTestId="import-apply-confirm"
      />
    </>
  );
}
