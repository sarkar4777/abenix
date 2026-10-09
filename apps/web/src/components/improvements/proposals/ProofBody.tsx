'use client';

import { useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Loader2, Pencil, RotateCw, Send, ShieldCheck } from 'lucide-react';
import {
  CHANGE_HELP, editableDiff, isWorking, parseDiff, proposalsApi, type Proposal,
} from '@/lib/improvement-proposals';
import { BeforeAfter, DiffView, Examples, FixedBroken, ProofSteps } from './parts';

export default function ProofBody({ p, onChange }: { p: Proposal; onChange?: (next: unknown) => void }) {
  const proof = p.proof;
  const steps = p.progress?.steps || [];
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const canRerun = p.state === 'failed_proof' || p.state === 'awaiting_approval' || p.state === 'rejected';

  async function rerun(withEdit: boolean) {
    setMsg(null);
    let diff: Record<string, unknown> | undefined;
    if (withEdit) {
      const parsed = parseDiff(text);
      if (parsed.error) {
        setMsg({ ok: false, text: parsed.error });
        return;
      }
      diff = parsed.diff || undefined;
    }
    setBusy(withEdit ? 'edit' : 'rerun');
    const r = await proposalsApi.rerun(p.id, diff);
    setBusy(null);
    if (r.error || !r.data) {
      setMsg({ ok: false, text: r.error || 'The proof did not start.' });
      return;
    }
    setEditing(false);
    setMsg({ ok: true, text: 'Proving it again. You can leave this page, it carries on and you get a notification.' });
    onChange?.(r.data);
  }

  async function askApproval() {
    setBusy('approve');
    const r = await proposalsApi.requestApproval(p.id);
    setBusy(null);
    if (r.error || !r.data) {
      setMsg({ ok: false, text: r.error || 'It could not be sent for approval.' });
      return;
    }
    setMsg({ ok: true, text: 'Sent for approval.' });
    onChange?.(r.data);
  }

  return (
    <div className="space-y-4" data-testid="proposal-proof" data-proposal-id={p.id} data-state={p.state}>
      {steps.length > 0 && (isWorking(p) || (p.state === 'failed_proof' && !proof)) && (
        <div className="rounded-lg border border-sky-500/30 bg-sky-500/5 p-3">
          <ProofSteps steps={steps} message={p.progress?.message} />
          {p.progress?.waiting ? (
            <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-200" data-testid="proof-waiting">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {p.progress.waiting}
            </p>
          ) : (
            isWorking(p) && (
              <p className="mt-2 text-[11px] text-slate-500">
                You can leave this page. The proof carries on and you get a notification when it is done.
              </p>
            )
          )}
        </div>
      )}

      {p.rationale && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500">Why this change</p>
          <p className="mt-0.5 break-words text-sm text-slate-200" data-testid="proposal-rationale">{p.rationale}</p>
        </div>
      )}

      {p.change_kind && (
        <div className="space-y-1.5">
          <p className="text-[11px] text-slate-400">
            {p.change_label}. {CHANGE_HELP[p.change_kind] || ''} Risk: {p.risk}.
          </p>
          {editing ? (
            <div className="space-y-2" data-testid="proposal-edit">
              <label className="text-[11px] text-slate-400" htmlFor={`edit-${p.id}`}>
                Edit the change. It is proved again before anyone can approve it.
              </label>
              <textarea
                id={`edit-${p.id}`}
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={10}
                spellCheck={false}
                className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 font-mono text-[11px] text-slate-100 focus:border-cyan-500/60 focus:outline-none"
                data-testid="proposal-edit-text"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => rerun(true)}
                  className="inline-flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                  data-testid="proposal-edit-save"
                >
                  {busy === 'edit' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />} Save and prove again
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <DiffView lines={p.diff?.preview?.lines || []} what={p.diff?.preview?.what} />
          )}
        </div>
      )}

      {p.state === 'failed_proof' && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-100" data-testid="proof-failed">
          <p className="font-medium text-amber-200">Did not pass, so nobody was asked to approve it.</p>
          <p className="mt-1">It is kept here so you can see what was tried.</p>
          {(proof?.bar_reasons?.length ? proof.bar_reasons : [p.error || 'The proof did not finish.']).map((r, i) => (
            <p key={i} className="mt-1">{r}</p>
          ))}
        </div>
      )}

      {proof && (
        <div className="space-y-4">
          <FixedBroken proof={proof} />
          {proof.scores && <BeforeAfter before={proof.scores.before} after={proof.scores.after} />}
          <p className="text-[11px] text-slate-400" data-testid="proof-replay">
            {proof.replay?.sampled
              ? `Replayed ${proof.replay.sampled} recent real inputs: ${proof.replay.changed} answered differently. ${proof.replay.watching_effects} actions were held and never ran.`
              : 'The agent had no recent runs to replay, so only the test cases were run.'}
            {proof.cases_run ? ` Ran ${proof.cases_run} test cases on both versions.` : ''}
            {proof.gating?.suites ? (proof.gating.passed === false ? ' It does not pass the release tests.' : ' It passes the release tests.') : ''}
          </p>
          <div>
            <p className="mb-1.5 text-[10px] uppercase tracking-wider text-slate-500">Real examples, now and with the fix</p>
            <Examples examples={proof.examples || []} />
          </div>
        </div>
      )}

      {p.state === 'awaiting_approval' && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-100"
          data-testid="proof-awaiting"
        >
          <ShieldCheck className="h-4 w-4 text-amber-300" />
          <span>
            It passed. Someone with Approve improvements signs it off in Approvals. The agent&apos;s author cannot approve it
            unless they work alone.
          </span>
          {p.approval_id ? (
            <Link href="/approvals" className="text-cyan-300 hover:underline" data-testid="proof-approval-link">
              Open Approvals
            </Link>
          ) : (
            <button
              type="button"
              onClick={askApproval}
              disabled={busy !== null}
              className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 px-2.5 py-1 text-amber-200 hover:bg-amber-500/10 disabled:opacity-50"
              data-testid="proof-request-approval"
            >
              {busy === 'approve' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />} Send for approval
            </button>
          )}
        </div>
      )}

      {p.state === 'rejected' && p.error && (
        <p className="rounded-lg border border-slate-700 bg-slate-900/40 p-3 text-xs text-slate-300" data-testid="proof-rejected">
          {p.error} The reason went back to the improver as a lesson.
        </p>
      )}

      {canRerun && !editing && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => rerun(false)}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
            data-testid="proof-rerun"
          >
            {busy === 'rerun' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />} Run the proof again
          </button>
          {p.change_kind && (
            <button
              type="button"
              onClick={() => {
                setText(editableDiff(p));
                setEditing(true);
                setMsg(null);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
              data-testid="proof-edit"
            >
              <Pencil className="h-3.5 w-3.5" /> Edit the change
            </button>
          )}
        </div>
      )}

      {msg && (
        <p role={msg.ok ? 'status' : 'alert'} className={`text-xs ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="proof-msg">
          {msg.text}
        </p>
      )}
    </div>
  );
}
