'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, FlaskConical, Loader2, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { useCapability } from '@/lib/capabilities';
import type { SuiteRow } from '@/lib/evals';

export default function SaveAsEvalCase({ executionId, agentId, agentName }: { executionId: string; agentId: string; agentName?: string }) {
  const { allowed } = useCapability('evals.manage');
  const [open, setOpen] = useState(false);
  if (!allowed || !agentId) return null;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-600/60 bg-slate-800/40 text-slate-200 text-xs font-semibold hover:bg-slate-700/60"
        title="Keep this run's input and output as a golden case"
        data-testid="execution-save-eval-case"
      >
        <FlaskConical className="w-3.5 h-3.5" /> Save as eval case
      </button>
      {open && <Dialog executionId={executionId} agentId={agentId} agentName={agentName} onClose={() => setOpen(false)} />}
    </>
  );
}

function Dialog({ executionId, agentId, agentName, onClose }: { executionId: string; agentId: string; agentName?: string; onClose: () => void }) {
  const { data: suites, isLoading } = useApi<SuiteRow[]>(`/api/evals/suites?agent_id=${agentId}`);
  const [choice, setChoice] = useState<string>('');
  const [newName, setNewName] = useState(`${agentName || 'Agent'} golden cases`);
  const [caseName, setCaseName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<{ suiteId: string; assertions: number } | null>(null);
  const target = choice || (suites && suites.length ? suites[0].id : 'new');

  async function save() {
    setBusy(true);
    setErr(null);
    let suiteId = target;
    if (target === 'new') {
      const s = await apiFetch<{ id: string }>('/api/evals/suites', {
        method: 'POST',
        body: JSON.stringify({ name: newName.trim(), agent_id: agentId }),
        throwOnError: false,
      });
      if (s.error || !s.data) {
        setBusy(false);
        return setErr(s.error || 'The suite could not be created.');
      }
      suiteId = s.data.id;
    }
    const r = await apiFetch<{ id: string; assertions: unknown[] }>(`/api/evals/suites/${suiteId}/cases/from-execution`, {
      method: 'POST',
      body: JSON.stringify({ execution_id: executionId, name: caseName.trim() || null }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error || !r.data) return setErr(r.error || 'The case could not be saved.');
    setDone({ suiteId, assertions: r.data.assertions.length });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="save-case-title">
      <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <h2 id="save-case-title" className="text-base font-semibold text-white">Save as eval case</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        {done ? (
          <div className="px-5 py-6 space-y-3">
            <p className="flex items-center gap-2 text-sm text-emerald-300"><CheckCircle2 className="w-4 h-4" /> Saved with {done.assertions} suggested assertion{done.assertions === 1 ? '' : 's'}.</p>
            <p className="text-xs text-slate-400">Each suggestion holds for this run. Tighten or remove them on the suite page.</p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Close</button>
              <Link href={`/evals/${done.suiteId}`} className="px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400" data-testid="save-case-open-suite">Open the suite</Link>
            </div>
          </div>
        ) : (
          <>
            <div className="px-5 py-4 space-y-4">
              <p className="text-xs text-slate-400">The run&apos;s input becomes the case, and its output seeds assertions you can edit. Later runs are checked against them.</p>
              <div>
                <div className="text-sm font-medium text-slate-200 mb-1.5">Suite</div>
                {isLoading ? (
                  <div className="h-10 rounded-md bg-slate-800/50 animate-pulse" />
                ) : (
                  <div className="space-y-1.5" role="radiogroup" aria-label="Suite">
                    {(suites || []).map((s) => (
                      <label key={s.id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 cursor-pointer ${target === s.id ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-700'}`}>
                        <input type="radio" name="suite" checked={target === s.id} onChange={() => setChoice(s.id)} className="accent-cyan-500" />
                        <span className="text-sm text-white">{s.name}</span>
                        <span className="text-xs text-slate-500 ml-auto">{s.case_count} case{s.case_count === 1 ? '' : 's'}</span>
                      </label>
                    ))}
                    <label className={`flex items-center gap-2 rounded-lg border px-3 py-2 cursor-pointer ${target === 'new' ? 'border-cyan-500/50 bg-cyan-500/5' : 'border-slate-700'}`}>
                      <input type="radio" name="suite" checked={target === 'new'} onChange={() => setChoice('new')} className="accent-cyan-500" data-testid="save-case-new-suite" />
                      <span className="text-sm text-white">New suite</span>
                      {target === 'new' && (
                        <input value={newName} onChange={(e) => setNewName(e.target.value)} className="ml-2 flex-1 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-sm text-white" aria-label="New suite name" data-testid="save-case-suite-name" />
                      )}
                    </label>
                  </div>
                )}
              </div>
              <div>
                <label htmlFor="sc-name" className="block text-sm font-medium text-slate-200 mb-1.5">Case name <span className="text-slate-500 font-normal">optional</span></label>
                <input id="sc-name" value={caseName} onChange={(e) => setCaseName(e.target.value)} placeholder="Taken from the first line of the input" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" />
              </div>
              {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
            </div>
            <div className="flex justify-end gap-2 px-5 py-4 border-t border-slate-800">
              <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
              <button type="button" onClick={save} disabled={busy || (target === 'new' && !newName.trim())} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="save-case-confirm">
                {busy && <Loader2 className="w-4 h-4 animate-spin" />} Save case
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
