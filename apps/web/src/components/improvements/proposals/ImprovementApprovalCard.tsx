'use client';

import { useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, Loader2, Pencil, Sparkles, XCircle } from 'lucide-react';
import { signoffApproval } from '@/lib/autonomy';
import { asProposal, editableDiff, fixedText, parseDiff, proposalsApi } from '@/lib/improvement-proposals';
import { BeforeAfter, DiffView, Examples, FixedBroken } from './parts';

const STATUS: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  denied: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  expired: 'bg-slate-500/15 text-slate-400 border-slate-500/40',
  returned: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
};

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

// what the parent needs to point at the release once the card leaves the list
export interface Decided {
  decision: 'approve' | 'deny' | 'edit';
  link: string | null;
  agentName: string | null;
}

export default function ImprovementApprovalCard({
  approval,
  onDecided,
}: {
  approval: Record<string, unknown>;
  onDecided?: (d: Decided) => void;
}) {
  const payload = obj(approval.payload);
  const p = asProposal(payload);
  const status = String(approval.status || 'pending');
  const pending = status === 'pending';
  const self = typeof payload.self_approval === 'string' ? payload.self_approval : null;
  const withdrawn = typeof payload.withdrawn === 'string' ? payload.withdrawn : null;
  const link = typeof payload.link === 'string' ? payload.link : null;
  const [mode, setMode] = useState<'idle' | 'edit' | 'reject'>('idle');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string; author?: boolean } | null>(null);
  const [details, setDetails] = useState(false);

  async function decide(decision: 'approve' | 'deny') {
    setMsg(null);
    if (decision === 'deny' && !text.trim()) {
      setMsg({ ok: false, text: 'Say why in a sentence. It goes back to the improver as a lesson.' });
      return;
    }
    setBusy(decision);
    const r = await signoffApproval(String(approval.id), decision, decision === 'deny' ? text.trim() : undefined);
    setBusy(null);
    if (r.error) {
      setMsg({ ok: false, text: r.error, author: r.code === 'AUTHOR_CANNOT_APPROVE' });
      return;
    }
    setMsg({ ok: true, text: decision === 'approve' ? 'Approved. It is released as a new revision and watched from now on.' : 'Rejected. The reason became a lesson.' });
    setMode('idle');
    onDecided?.({ decision, link, agentName: p.agent.name || null });
  }

  async function editAndProve() {
    const parsed = parseDiff(text);
    if (parsed.error || !parsed.diff) {
      setMsg({ ok: false, text: parsed.error || 'The change is empty.' });
      return;
    }
    setBusy('edit');
    const r = await proposalsApi.rerun(p.id, parsed.diff);
    setBusy(null);
    if (r.error) {
      setMsg({ ok: false, text: r.error });
      return;
    }
    setMode('idle');
    setMsg({ ok: true, text: 'The edited fix is being proved. When it passes it comes back here for approval.' });
    onDecided?.({ decision: 'edit', link, agentName: p.agent.name || null });
  }

  const proof = p.proof;
  return (
    <div
      className="mb-3 rounded-xl border border-slate-700/50 bg-slate-800/40 p-4"
      data-testid="improvement-approval-card"
      data-approval-id={String(approval.id || '')}
      data-status={status}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0 text-cyan-400" />
        <h3 className="min-w-0 flex-1 break-words text-sm font-semibold text-white">{String(approval.title || 'Release a fix')}</h3>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${STATUS[status] || STATUS.expired}`} data-testid="improvement-approval-status">
          {withdrawn && status === 'expired' ? 'withdrawn' : status}
        </span>
        <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-300" data-testid="approval-gate-kind">
          agent improvement
        </span>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">
        {p.agent.name ? `${p.agent.name}: ` : ''}
        {p.cluster?.title || p.change_label}. {fixedText(proof)}.
      </p>
      {pending &&
        (self ? (
          <p className="mt-1 text-[11px] text-cyan-200" data-testid="approval-self-approval">{self}</p>
        ) : (
          <p className="mt-1 text-[11px] text-slate-500">Needs Approve improvements, and not the person who built the agent.</p>
        ))}
      {withdrawn && !msg && <p className="mt-1 text-[11px] text-slate-400">{withdrawn}</p>}

      {p.rationale && <p className="mt-3 break-words text-sm text-slate-200">{p.rationale}</p>}

      <div className="mt-3 space-y-3">
        {mode === 'edit' ? (
          <div className="space-y-2" data-testid="improvement-approval-edit">
            <label className="text-[11px] text-slate-400" htmlFor={`ia-${String(approval.id)}`}>
              Edit the change. It is proved again, then it comes back here.
            </label>
            <textarea
              id={`ia-${String(approval.id)}`}
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={9}
              spellCheck={false}
              className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 font-mono text-[11px] text-slate-100 focus:border-cyan-500/60 focus:outline-none"
              data-testid="improvement-approval-edit-text"
            />
          </div>
        ) : (
          <DiffView lines={p.diff?.preview?.lines || []} what={p.diff?.preview?.what} />
        )}
        {proof && <FixedBroken proof={proof} />}
        <button type="button" onClick={() => setDetails((v) => !v)} className="text-[11px] text-slate-400 hover:text-white" aria-expanded={details}>
          {details ? 'Hide' : 'Show'} the numbers and three real examples
        </button>
        {details && proof && (
          <div className="space-y-3">
            {proof.scores && <BeforeAfter before={proof.scores.before} after={proof.scores.after} />}
            <Examples examples={proof.examples || []} />
          </div>
        )}
      </div>

      {pending && mode === 'reject' && (
        <div className="mt-3">
          <label className="text-[11px] text-slate-400" htmlFor={`ir-${String(approval.id)}`}>
            Why not? It goes back to the improver as a lesson.
          </label>
          <input
            id={`ir-${String(approval.id)}`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={2000}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white focus:border-cyan-500/60 focus:outline-none"
            data-testid="improvement-approval-reject-note"
          />
        </div>
      )}

      {pending && (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          {mode === 'idle' && (
            <>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => decide('approve')}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-medium text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
                data-testid="improvement-approve"
              >
                {busy === 'approve' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />} Approve
              </button>
              <button
                type="button"
                disabled={busy !== null || !p.id}
                onClick={() => {
                  setText(editableDiff(p));
                  setMode('edit');
                  setMsg(null);
                }}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-700/50 disabled:opacity-50"
                data-testid="improvement-edit-approve"
              >
                <Pencil className="h-3.5 w-3.5" /> Edit and approve
              </button>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => {
                  setText('');
                  setMode('reject');
                  setMsg(null);
                }}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/25 disabled:opacity-50"
                data-testid="improvement-reject"
              >
                <XCircle className="h-3.5 w-3.5" /> Reject
              </button>
            </>
          )}
          {mode === 'edit' && (
            <>
              <button
                type="button"
                disabled={busy !== null}
                onClick={editAndProve}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                data-testid="improvement-edit-save"
              >
                {busy === 'edit' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pencil className="h-3.5 w-3.5" />} Prove the edited fix
              </button>
              <button type="button" onClick={() => setMode('idle')} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
                Cancel
              </button>
            </>
          )}
          {mode === 'reject' && (
            <>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => decide('deny')}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/25 disabled:opacity-50"
                data-testid="improvement-reject-confirm"
              >
                {busy === 'deny' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />} Reject with this reason
              </button>
              <button type="button" onClick={() => setMode('idle')} className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
                Cancel
              </button>
            </>
          )}
        </div>
      )}

      {msg && (
        <p role={msg.ok ? 'status' : 'alert'} className={`mt-2 text-xs ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="improvement-approval-msg">
          {msg.text}
          {msg.author && (
            <>
              {' '}
              <Link href="/settings/team" className="text-cyan-300 underline">Invite a teammate</Link>
            </>
          )}
        </p>
      )}
      {p.agent.id && p.id && (
        <Link
          href={`/agents/${encodeURIComponent(p.agent.id)}/improvements?proposal=${encodeURIComponent(p.id)}`}
          className="mt-2 inline-block text-[11px] text-cyan-300 hover:underline"
        >
          Open the full proof
        </Link>
      )}
    </div>
  );
}
