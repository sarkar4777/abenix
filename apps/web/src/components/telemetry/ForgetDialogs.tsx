'use client';

import { useEffect, useState } from 'react';
import { Archive, CheckCircle2, Loader2 } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { ago } from '@/lib/telemetry/format';
import { OFFLINE_FOR, forgetAll, forgetOne, forgetPreview, globProblem, offlineLabel, type BulkQuery, type BulkResult } from '@/lib/telemetry/forget';
import { toastSuccess } from '@/stores/toastStore';

const KEPT = 'Its history is kept, so charts and reports still show it. If it reports again it comes back on its own.';

// one asset or part: confirm, and a second confirm if it is still online
export function ForgetOneDialog({ group, node, device, onClose, onDone }: { group: string; node: string; device: string; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const target = device ? `${node} / ${device}` : node;
  const what = device ? 'this part' : 'this asset and all its parts';

  async function go(force: boolean) {
    setBusy(true);
    setErr(null);
    const r = await forgetOne(group, node, device || null, force);
    setBusy(false);
    if (r.kind === 'done') {
      toastSuccess(`${target} forgotten`, 'Its place in the workspace limit is free again. History is kept.');
      onDone();
    } else if (r.kind === 'online') setOnline(r.message);
    else setErr(r.message);
  }

  if (online) {
    return (
      <ConfirmModal
        open
        onClose={() => !busy && onClose()}
        onConfirm={() => go(true)}
        loading={busy}
        icon={Archive}
        title={`${target} is online. Forget it anyway?`}
        description={`${online} Forget it anyway only if it has really stopped, or to clear it before it is moved or renamed. ${KEPT}`}
        confirmLabel="Forget anyway"
        confirmTestId="tel-forget-force"
      >
        {err && <p className="text-xs text-rose-300" role="alert">{err}</p>}
      </ConfirmModal>
    );
  }
  return (
    <ConfirmModal
      open
      onClose={() => !busy && onClose()}
      onConfirm={() => go(false)}
      loading={busy}
      variant="warning"
      icon={Archive}
      title={`Forget ${target}?`}
      description={`Abenix stops listing ${what} and frees its place in the workspace limit. ${KEPT} This is recorded in the audit log.`}
      confirmLabel="Forget"
      confirmTestId="tel-forget-confirm"
    >
      {err && <p className="text-xs text-rose-300" role="alert">{err}</p>}
    </ConfirmModal>
  );
}

// many at once: filters, a dry run with a count and a sample, a confirm, then progress
export function BulkForgetDialog({ groups, sources, initial, onClose, onDone }: {
  groups: string[];
  sources: Array<{ id: string; name: string }>;
  initial?: Partial<BulkQuery> & { autoPreview?: boolean };
  onClose: () => void;
  onDone: () => void;
}) {
  const [offlineFor, setOfflineFor] = useState(initial?.offline_for_s ?? 3600);
  const [group, setGroup] = useState(initial?.group ?? '');
  const [glob, setGlob] = useState(initial?.node_glob ?? '');
  const [source, setSource] = useState(initial?.connection_id ?? '');
  const [preview, setPreview] = useState<BulkResult | null>(null);
  const [step, setStep] = useState<'pick' | 'confirm' | 'running' | 'done'>('pick');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState({ done: 0, remaining: 0 });
  const gErr = globProblem(glob);
  const query: BulkQuery = { offline_for_s: offlineFor, group: group || undefined, node_glob: glob.trim() || undefined, connection_id: source || undefined };

  async function runPreview() {
    if (gErr) return;
    setBusy(true);
    setErr(null);
    const r = await forgetPreview(query);
    setBusy(false);
    setPreview(r.result);
    setErr(r.error);
  }

  useEffect(() => {
    if (initial?.autoPreview) void runPreview();
  }, []);

  // the preview belongs to the filters it was made with
  useEffect(() => { setPreview(null); }, [offlineFor, group, glob, source]);

  async function run() {
    setStep('running');
    setErr(null);
    const total = preview?.matched ?? 0;
    setProgress({ done: 0, remaining: total });
    const r = await forgetAll(query, (done, remaining) => setProgress({ done, remaining }));
    if (r.error) { setErr(r.error); setStep('pick'); return; }
    setProgress({ done: r.forgotten, remaining: 0 });
    setStep('done');
    toastSuccess(`${r.forgotten} forgotten`, 'Their places in the workspace limit are free again. History is kept.');
    onDone();
  }

  const box = 'w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600';
  const total = preview?.matched ?? 0;
  const pct = total ? Math.round((progress.done / Math.max(total, progress.done + progress.remaining)) * 100) : 0;

  return (
    <ResponsiveModal open onClose={step === 'running' ? () => {} : onClose} title="Forget offline devices" icon={<Archive className="h-4 w-4" />} maxWidth="max-w-xl">
      <div className="space-y-3" data-testid="tel-bulk-forget" data-step={step}>
        <p className="text-sm text-slate-300">Forgetting takes devices off the list and frees their places in the workspace limit. {KEPT}</p>

        {step === 'pick' && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-300">Offline for</span>
                <select value={offlineFor} onChange={(e) => setOfflineFor(Number(e.target.value))} className={box} data-testid="tel-forget-offline-for">
                  {OFFLINE_FOR.map((o) => <option key={o.s} value={o.s}>{o.label}</option>)}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-300">Group <span className="font-normal text-slate-500">(optional)</span></span>
                <select value={group} onChange={(e) => setGroup(e.target.value)} className={box} data-testid="tel-forget-group">
                  <option value="">Every group</option>
                  {groups.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-300">Asset name pattern <span className="font-normal text-slate-500">(optional)</span></span>
                <input value={glob} onChange={(e) => setGlob(e.target.value)} placeholder="uat-*" className={`${box} font-mono ${gErr ? 'border-rose-500/60' : ''}`} data-testid="tel-forget-glob" />
                {gErr ? <span className="mt-1 block text-xs text-rose-300" role="alert">{gErr}</span> : <span className="mt-1 block text-xs text-slate-500">* matches anything. Example: truck-*</span>}
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-300">Source <span className="font-normal text-slate-500">(optional)</span></span>
                <select value={source} onChange={(e) => setSource(e.target.value)} className={box} data-testid="tel-forget-source">
                  <option value="">Every source</option>
                  {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </label>
            </div>

            {preview && (
              <div className="rounded-lg border border-slate-700/60 p-3 text-sm" data-testid="tel-forget-preview" data-matched={preview.matched}>
                <p className={preview.matched ? 'text-white' : 'text-slate-300'}>
                  {preview.matched
                    ? `${preview.matched.toLocaleString()} device${preview.matched === 1 ? '' : 's'} offline for ${offlineLabel(offlineFor)} match.`
                    : `Nothing matches: no device has been offline for ${offlineLabel(offlineFor)} with these filters.`}
                </p>
                {preview.sample.length > 0 && (
                  <ul className="mt-2 max-h-48 space-y-0.5 overflow-y-auto text-xs">
                    {preview.sample.map((d) => (
                      <li key={`${d.group}/${d.node}/${d.device}`} className="flex gap-2">
                        <span className="min-w-0 flex-1 truncate font-mono text-slate-200">{d.group} / {d.node}{d.device ? ` / ${d.device}` : ''}</span>
                        <span className="shrink-0 text-slate-500">offline {ago(d.offline_at ?? d.last_seen ?? null)}</span>
                      </li>
                    ))}
                    {preview.matched > preview.sample.length && <li className="text-slate-500">and {(preview.matched - preview.sample.length).toLocaleString()} more</li>}
                  </ul>
                )}
              </div>
            )}
            {err && <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert">{err}</p>}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">Cancel</button>
              {preview && preview.matched > 0 ? (
                <button type="button" onClick={() => setStep('confirm')} className="min-h-[40px] rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-400" data-testid="tel-forget-next">
                  Forget {preview.matched.toLocaleString()}
                </button>
              ) : (
                <button type="button" onClick={runPreview} disabled={busy || !!gErr} title={gErr ? 'Fix the pattern first' : undefined} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:opacity-60" data-testid="tel-forget-preview-run">
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />} See what matches
                </button>
              )}
            </div>
          </>
        )}

        {step === 'confirm' && (
          <>
            <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-50" data-testid="tel-forget-confirm-text">
              Forget {total.toLocaleString()} device{total === 1 ? '' : 's'} offline for {offlineLabel(offlineFor)}{group ? ` in ${group}` : ''}{glob.trim() ? ` named like ${glob.trim()}` : ''}? They leave the list now. History is kept, and any that report again come back. This is recorded in the audit log.
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setStep('pick')} className="min-h-[40px] rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">Back</button>
              <button type="button" onClick={run} className="min-h-[40px] rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-400" data-testid="tel-forget-run">Yes, forget them</button>
            </div>
          </>
        )}

        {(step === 'running' || step === 'done') && (
          <div className="space-y-2" data-testid="tel-forget-progress">
            <div className="h-2 overflow-hidden rounded-full bg-slate-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full bg-amber-400 transition-[width]" style={{ width: `${step === 'done' ? 100 : pct}%` }} />
            </div>
            <p className="flex items-center gap-1.5 text-sm text-slate-200">
              {step === 'running' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4 text-emerald-300" />}
              {step === 'running' ? `Forgotten ${progress.done.toLocaleString()} so far, ${progress.remaining.toLocaleString()} to go` : `Done. ${progress.done.toLocaleString()} forgotten.`}
            </p>
            {step === 'done' && (
              <div className="flex justify-end">
                <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400" data-testid="tel-forget-close">Done</button>
              </div>
            )}
          </div>
        )}
      </div>
    </ResponsiveModal>
  );
}
