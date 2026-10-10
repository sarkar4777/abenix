'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ReasonDialog } from '@/components/decisions/SignOff';
import { decisionErrorText } from '@/lib/decisionValues';
import { AlertTriangle, CheckCircle2, Loader2, ShieldCheck, Undo2, XCircle } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { apiFetch } from '@/lib/api-client';
import { isActionGate, levelLabel, relTime, signoffApproval } from '@/lib/autonomy';
import { RELEASE_GATE, canSign, refreshInboxCounts, useInboxCounts, type SignableRow } from '@/lib/inbox';
import {
  GATE_LABEL, LIFECYCLE_KINDS, approvalEffect, askedBecause, changesText, confirmApproveText, decisionLink,
  needsApproveConfirm, requesterName, shortSummary, signoffError,
} from '@/lib/approvalText';
import { toastSuccess } from '@/stores/toastStore';
import ApprovalActionRow from '@/components/autonomy/ApprovalActionRow';

interface Row extends SignableRow {
  title: string;
  status: string;
  payload: Record<string, unknown>;
  created_at?: string | null;
  expires_at?: string | null;
  requested_by_name?: string | null;
  change_note?: string | null;
  changes?: number | null;
  can_sign?: boolean;
  kind_label?: string | null;
  summary?: string | null;
}

function evidenceLink(row: Row): { href: string; label: string } | null {
  const p = row.payload || {};
  if ((row.gate_kind === 'decision_publish' || row.gate_kind === 'decision_reattest') && typeof p.link === 'string') return { href: p.link, label: 'Review the rules' };
  if (row.gate_kind === 'decision_tier_change' || (row.gate_kind && LIFECYCLE_KINDS.has(row.gate_kind))) {
    const href = decisionLink(row);
    return href ? { href, label: 'Open the decision' } : null;
  }
  if (row.gate_kind === 'autonomy.promote' && typeof p.grant_id === 'string') {
    return { href: `/autonomy/${encodeURIComponent(p.grant_id)}`, label: 'See the evidence' };
  }
  return null;
}

function promotionLine(row: Row): string {
  const p = row.payload || {};
  const agent = (p.agent as { name?: string } | undefined)?.name;
  const from = typeof p.from === 'number' ? p.from : null;
  const to = typeof p.to === 'number' ? p.to : null;
  const move = from !== null && to !== null ? `${levelLabel(from)} to ${levelLabel(to)}` : 'move up a level';
  return agent ? `${agent}: ${move}` : move;
}

type Decide = (id: string, d: 'approve' | 'deny' | 'return', reason?: string) => Promise<string | null>;

// a compact version of the Approvals page card, approve, deny or send back right here
export function QuickRow({ row, busy, onDecide }: { row: Row; busy: boolean; onDecide: Decide }) {
  const [err, setErr] = useState<string | null>(null);
  const [asking, setAsking] = useState<'deny' | 'return' | null>(null);
  const [confirming, setConfirming] = useState(false);
  const text = row.gate_kind === 'autonomy.promote' ? promotionLine(row) : shortSummary(row) || row.summary || null;
  const link = evidenceLink(row);
  const who = requesterName(row);
  const why = askedBecause(row);
  const changes = row.gate_kind === 'decision_publish' ? changesText(row) : null;
  // the server's label wins so Needs you and Approvals name a request the same way
  const label = row.kind_label || (row.gate_kind ? GATE_LABEL[row.gate_kind] : undefined) || undefined;
  const canReturn = !row.id.startsWith('hitl:') && !!row.gate_kind && row.gate_kind.startsWith('decision_');
  const confirm = needsApproveConfirm(row) ? confirmApproveText(row) : null;
  const approve = async () => {
    setErr(null);
    setConfirming(false);
    const e = await onDecide(row.id, 'approve');
    if (e) { setErr(e); return; }
    // the row leaves the list, so say what the approval did
    const after = approvalEffect(row, 'after', 'approve');
    const who = requesterName(row);
    toastSuccess(`Approved: ${row.title || 'the request'}`, after || `${who || 'The person who asked'} is told.`);
  };
  return (
    <div className="mb-3 rounded-xl border border-slate-700/50 bg-slate-800/40 p-4" data-testid="inbox-approval" data-approval-id={row.id} data-kind={row.gate_kind || ''}>
      {asking && (
        <ReasonDialog
          title={asking === 'deny' ? 'Deny this request?' : 'Send it back for changes?'}
          intro={asking === 'deny'
            ? `${row.title || 'This request'} will not go ahead. Say why, so the person who asked knows what to change.`
            : `${row.title || 'This request'} goes back to the person who asked. Say what needs to change.`}
          verb={asking === 'deny' ? 'Deny' : 'Send back'}
          placeholder={asking === 'deny' ? 'what is wrong, or what would make it acceptable' : 'what to change before it comes back'}
          testId={asking === 'deny' ? 'deny-dialog' : 'return-dialog'}
          onClose={() => setAsking(null)}
          onConfirm={async (reason) => {
            const e = await onDecide(row.id, asking, reason);
            if (!e) setAsking(null);
            return e;
          }}
        />
      )}
      {confirm && (
        <ConfirmModal
          open={confirming}
          onClose={() => setConfirming(false)}
          onConfirm={approve}
          title={confirm.title}
          description={confirm.body}
          confirmLabel="Approve"
          variant="warning"
          confirmTestId="inbox-approve-confirm"
        />
      )}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <ShieldCheck className="h-4 w-4 shrink-0 text-cyan-400" />
            <h3 className="min-w-0 break-words text-sm font-semibold text-white">{row.title || 'Approval requested'}</h3>
            {label && (
              <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-300" data-testid="inbox-kind">{label}</span>
            )}
          </div>
          {text && (
            <p className="mt-1 break-words text-xs text-slate-300" data-testid="inbox-summary">
              {text}{changes ? ` ${changes}.` : ''}
            </p>
          )}
          {why && <p className="mt-1 break-words text-xs text-slate-400" data-testid="inbox-why">Asked because: “{why}”</p>}
          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-500">
            {(who || row.created_at) && (
              <span data-testid="inbox-requester">Asked{who ? ` by ${who}` : ''}{row.created_at ? ` ${relTime(row.created_at)}` : ''}</span>
            )}
            {link && <Link href={link.href} className="text-cyan-300 hover:underline" data-testid="inbox-evidence">{link.label}</Link>}
          </div>
        </div>
        <div className="flex w-full shrink-0 flex-wrap gap-2 sm:w-auto">
          <button
            type="button"
            disabled={busy}
            onClick={() => (confirm ? setConfirming(true) : approve())}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50 sm:flex-none"
            data-testid="inbox-approve"
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => { setErr(null); setAsking('deny'); }}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-2 text-xs font-medium text-rose-300 hover:bg-rose-500/25 disabled:opacity-50 sm:flex-none"
            data-testid="inbox-deny"
          >
            <XCircle className="h-3.5 w-3.5" /> Deny
          </button>
          {canReturn && (
            <button
              type="button"
              disabled={busy}
              onClick={() => { setErr(null); setAsking('return'); }}
              className="flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-300 hover:bg-amber-500/20 disabled:opacity-50 sm:flex-none"
              data-testid="inbox-return"
            >
              <Undo2 className="h-3.5 w-3.5" /> Return for changes
            </button>
          )}
        </div>
      </div>
      {err && <p className="mt-2 text-xs text-rose-300" role="alert">{err}</p>}
    </div>
  );
}

export default function ApprovalsPanel({
  me,
  caps,
  onCount,
}: {
  me: { id: string; role?: string };
  caps: readonly string[] | undefined;
  onCount?: (n: number) => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [yoursWaiting, setYoursWaiting] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await apiFetch<Row[]>('/api/approvals?mine=1&status=pending', { silent: true });
    setLoading(false);
    if (r.error && !r.data) {
      setError('Approvals could not be loaded. Check your connection and try again.');
      return;
    }
    setError(null);
    const open = (r.data || []).filter((a) => a.status === 'pending' && a.gate_kind !== RELEASE_GATE);
    const mine = open.filter((a) => a.can_sign ?? canSign(a, me, caps));
    setRows(mine);
    setYoursWaiting(open.filter((a) => !mine.includes(a) && !!a.requested_by && String(a.requested_by) === String(me.id)).length);
    onCount?.(mine.length);
  }, [me, caps, onCount]);

  useEffect(() => {
    load();
  }, [load]);

  // the badge and the list stay in step: look again when the count moves, and now and then
  const { counts } = useInboxCounts();
  const approvalsCount = counts?.counts?.approvals;
  useEffect(() => {
    if (approvalsCount !== undefined) load();
  }, [approvalsCount, load]);
  useEffect(() => {
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const decide = async (id: string, decision: 'approve' | 'deny' | 'return', reason?: string, edited?: Record<string, unknown>) => {
    setBusyId(id);
    const r = await signoffApproval(id, decision, reason, edited);
    setBusyId(null);
    await load();
    refreshInboxCounts();
    return r.error ? signoffError(r.code, decisionErrorText(r.code, r.error, r.details), reason) : null;
  };

  const yours = yoursWaiting > 0 && (
    <p className="mb-3 text-xs text-slate-400" data-testid="inbox-yours-waiting">
      {yoursWaiting === 1 ? 'One request of yours is' : `${yoursWaiting} requests of yours are`} waiting on someone else.{' '}
      <Link href="/approvals" className="text-cyan-300 hover:underline">Follow them on Approvals</Link>
    </p>
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading approvals
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
        <AlertTriangle className="h-4 w-4" /> {error}
        <button type="button" onClick={load} className="ml-auto text-xs underline">Try again</button>
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <>
        {yours}
        <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center" data-testid="inbox-approvals-empty">
          <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-400/40" />
          <p className="text-sm text-slate-400">No approvals waiting on you. Requests you are allowed to sign show here.</p>
        </div>
      </>
    );
  }
  return (
    <div data-testid="inbox-approvals">
      {yours}
      {rows.map((row) =>
        isActionGate(row.gate_kind) ? (
          <ApprovalActionRow
            key={row.id}
            row={{ ...row, status: row.status, title: row.title }}
            onDecide={decide}
            busy={busyId === row.id}
          />
        ) : (
          <QuickRow key={row.id} row={row} busy={busyId === row.id} onDecide={decide} />
        ),
      )}
    </div>
  );
}
