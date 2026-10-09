'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { CheckCircle2, ChevronDown, ChevronRight, History, Loader2, RefreshCw, Undo2, XCircle } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import type { ProposalRow } from '@/lib/improvements';
import { money, pct, proposalsApi, rate, watchLeft, type Measures, type WatchResult } from '@/lib/improvement-proposals';
import { StateChip } from './parts';
import ProofBody from './ProofBody';
import { focusedProposalId, useProposal } from './useProposal';

interface Row {
  label: string;
  before: string;
  after: string;
  worse: boolean;
}

export function measureRows(w: WatchResult | null): Row[] {
  const o: Partial<Measures> = w?.old || {};
  const n: Partial<Measures> = w?.new || {};
  const fr = (m: Partial<Measures>) => rate(m.failures, m.runs);
  const td = (m: Partial<Measures>) => rate(m.thumbs_down, m.thumbs_total);
  const acc = (m: Partial<Measures>) => rate(m.accurate, m.scored);
  const worse = (w?.worse || []).join(' ');
  return [
    { label: 'Runs', before: String(o.runs ?? 0), after: String(n.runs ?? 0), worse: false },
    { label: 'Failed runs', before: pct(fr(o)), after: pct(fr(n)), worse: worse.includes('Failed runs') },
    {
      label: 'Thumbs down',
      before: o.thumbs_total ? `${pct(td(o))} of ${o.thumbs_total}` : 'none yet',
      after: n.thumbs_total ? `${pct(td(n))} of ${n.thumbs_total}` : 'none yet',
      worse: worse.includes('Thumbs down'),
    },
    { label: 'Cost per run', before: money(o.cost_avg ?? null), after: money(n.cost_avg ?? null), worse: worse.includes('Cost per run') },
    {
      label: 'Autonomy accuracy',
      before: o.scored ? pct(acc(o)) : 'no scored actions',
      after: n.scored ? pct(acc(n)) : 'no scored actions',
      worse: worse.includes('accuracy'),
    },
    {
      label: 'Same mistake again',
      before: String(o.cluster_lessons ?? 0),
      after: String(n.cluster_lessons ?? 0),
      worse: worse.includes('came back'),
    },
    { label: 'Drift alerts', before: '', after: (n.drift || []).length ? (n.drift || []).join(', ') : 'none', worse: worse.includes('drift') },
  ];
}

function Spark({ points, pick, label }: { points: NonNullable<WatchResult['points']>; pick: (p: NonNullable<WatchResult['points']>[number]) => number | null; label: string }) {
  const vals = points.map(pick).map((v) => (v === null || !Number.isFinite(v) ? 0 : v));
  if (vals.length < 2) return null;
  const max = Math.max(...vals, 0.01);
  const w = 120;
  const h = 28;
  const d = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`).join(' ');
  return (
    <figure className="flex items-center gap-2 text-[10px] text-slate-500">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${label} over the watch period`}>
        <polyline points={d} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-cyan-400" />
      </svg>
      <figcaption>{label}</figcaption>
    </figure>
  );
}

export default function ReleaseWatch({ proposal }: { proposal: ProposalRow }) {
  const { p, setP } = useProposal(proposal);
  const w = p.watch_result;
  const outcome = p.state === 'kept' ? 'kept' : p.state === 'rolled_back' ? 'rolled_back' : w?.outcome || 'watching';
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (focusedProposalId() === p.id) {
      setOpen(true);
      ref.current?.scrollIntoView({ block: 'start' });
    }
  }, [p.id]);

  async function checkNow() {
    setBusy('check');
    setMsg(null);
    const r = await proposalsApi.watchCheck(p.id);
    setBusy(null);
    if (r.error || !r.data) {
      setMsg({ ok: false, text: r.error || 'The check did not run.' });
      return;
    }
    setP(r.data);
    setMsg({ ok: true, text: 'Checked just now.' });
  }

  async function rollBack() {
    setBusy('rollback');
    setMsg(null);
    const r = await proposalsApi.rollback(p.id, reason.trim() || 'Rolled back by a person.');
    setBusy(null);
    setConfirm(false);
    if (r.error || !r.data) {
      setMsg({ ok: false, text: r.error || 'It could not be rolled back.' });
      return;
    }
    setP(r.data);
  }

  const rows = measureRows(w);
  const target = p.watch_runs_target || 0;
  const runs = w?.new?.runs ?? 0;

  return (
    <div ref={ref} className="rounded-xl border border-slate-700/60 bg-slate-800/30 p-4" data-testid="release-watch" data-proposal-id={p.id} data-outcome={outcome}>
      <div className="flex flex-wrap items-center gap-2">
        <StateChip p={p} />
        <span className="min-w-0 break-words text-sm text-white">{p.cluster?.title || p.change_label}</span>
      </div>
      <p className="mt-1 text-[11px] text-slate-500">
        {p.change_label}
        {w?.approved_by_name ? `, approved by ${w.approved_by_name}` : ''}
        {w?.started_at ? `, released ${new Date(w.started_at).toLocaleString()}` : ''}
      </p>

      {outcome === 'watching' && (
        <p className="mt-2 text-xs text-slate-300" data-testid="release-watch-progress">
          Watching: {runs} of {target || '?'} runs on the new version, {watchLeft(p.watch_until) || 'until the next check'}. Worse than
          the old version on any measure rolls it back on its own.
        </p>
      )}
      {outcome === 'kept' && (
        <p className="mt-2 flex items-start gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2.5 text-xs text-emerald-200" data-testid="release-kept">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> Kept. It did as well or better than the old version over {runs} runs, so the
          lessons it fixed are closed.
        </p>
      )}
      {outcome === 'rolled_back' && (
        <div className="mt-2 rounded-lg border border-rose-500/40 bg-rose-500/5 p-2.5 text-xs text-rose-100" data-testid="release-rolled-back">
          <p className="flex items-center gap-1.5 font-medium text-rose-200">
            <XCircle className="h-3.5 w-3.5" /> {w?.automatic ? 'Rolled back automatically' : `Rolled back by ${w?.rolled_back_by_name || 'a person'}`}
          </p>
          <p className="mt-1 break-words" data-testid="release-rollback-reason">{w?.reason || 'No reason was recorded.'}</p>
          <p className="mt-1 text-rose-200/70">The agent is back on the version before the release. The approver and the owner were told.</p>
        </div>
      )}
      {outcome === 'stopped' && (
        <p className="mt-2 rounded-lg border border-slate-700 bg-slate-900/40 p-2.5 text-xs text-slate-300" data-testid="release-stopped">
          {w?.reason || 'The watch stopped.'}
        </p>
      )}

      {w?.old || w?.new ? (
        <div className="mt-3 overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full table-fixed text-[11px]" data-testid="release-measures">
            <thead className="bg-slate-900/60 text-slate-500">
              <tr>
                <th className="w-[38%] px-2 py-1.5 text-left font-normal">Measure</th>
                <th className="px-2 py-1.5 text-left font-normal">Old version</th>
                <th className="px-2 py-1.5 text-left font-normal">New version</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-t border-slate-800">
                  <td className="px-2 py-1.5 text-slate-300">{r.label}</td>
                  <td className="break-words px-2 py-1.5 text-slate-400">{r.before}</td>
                  <td className={`break-words px-2 py-1.5 ${r.worse ? 'font-medium text-rose-300' : 'text-slate-200'}`}>{r.after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        outcome === 'watching' && <p className="mt-2 text-[11px] text-slate-500">No live results yet. The first check runs within five minutes.</p>
      )}
      {w?.points && w.points.length > 1 && (
        <div className="mt-2 flex flex-wrap gap-4">
          <Spark points={w.points} pick={(x) => x.failure_rate} label="Failed runs" />
          <Spark points={w.points} pick={(x) => x.thumbs_down_rate} label="Thumbs down" />
        </div>
      )}
      {w?.checked_at && <p className="mt-1.5 text-[10px] text-slate-600">Last checked {new Date(w.checked_at).toLocaleString()}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {outcome === 'watching' && p.state === 'released' && (
          <>
            <button
              type="button"
              onClick={checkNow}
              disabled={busy !== null}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50"
              data-testid="release-check-now"
            >
              {busy === 'check' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />} Check now
            </button>
            <button
              type="button"
              onClick={() => setConfirm(true)}
              disabled={busy !== null}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/40 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-500/10 disabled:opacity-50"
              data-testid="release-rollback"
            >
              <Undo2 className="h-3.5 w-3.5" /> Roll back now
            </button>
          </>
        )}
        {p.agent.id && (
          <Link href={`/agents/${encodeURIComponent(p.agent.id)}/info`} className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" data-testid="release-history-link">
            <History className="h-3.5 w-3.5" /> Revision history
          </Link>
        )}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white"
          data-testid="release-proof-toggle"
        >
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />} The proof
        </button>
      </div>
      {msg && (
        <p role={msg.ok ? 'status' : 'alert'} className={`mt-2 text-xs ${msg.ok ? 'text-emerald-300' : 'text-rose-300'}`} data-testid="release-msg">
          {msg.text}
        </p>
      )}
      {open && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <ProofBody p={p} />
        </div>
      )}

      <ConfirmModal
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={rollBack}
        title="Roll back this fix?"
        description="The agent goes back to the version before the release at once. Rolling back never needs an approval. The approver and the owner are told."
        confirmLabel="Roll back"
        variant="warning"
        loading={busy === 'rollback'}
        confirmTestId="release-rollback-confirm"
      >
        <label className="mt-2 block text-xs text-slate-400" htmlFor={`rb-${p.id}`}>
          Why, in a sentence (optional)
        </label>
        <input
          id={`rb-${p.id}`}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          maxLength={2000}
          className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white focus:border-cyan-500/60 focus:outline-none"
          data-testid="release-rollback-reason-input"
        />
      </ConfirmModal>
    </div>
  );
}
