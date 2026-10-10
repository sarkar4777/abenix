'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CheckCircle2, XCircle, Clock, Loader2, ShieldCheck, AlertTriangle,
  RefreshCw, ChevronDown, ChevronRight, Eye, Inbox,
} from 'lucide-react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import { isActionGate, levelLabel, signoffApproval } from '@/lib/autonomy';
import ApprovalActionRow from '@/components/autonomy/ApprovalActionRow';
import ReviewQueue from '@/components/autonomy/ReviewQueue';
import ImprovementApprovalCard, { type Decided } from '@/components/improvements/proposals/ImprovementApprovalCard';
import ReleasedNext from '@/components/improvements/proposals/ReleasedNext';
import PageHeader from '@/components/layout/PageHeader';
import { useAuth } from '@/contexts/AuthContext';
import { InviteApprover, ReasonDialog, SelfApprovedBadge, SoleOperatorDialog } from '@/components/decisions/SignOff';
import { decisionErrorText } from '@/lib/decisionValues';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { tierName } from '@/lib/decisions';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { approvalEffect as decisionEffect, askedBecause, changesText, confirmApproveText, refusal, requesterName, signerName, signoffError, takesOutOfService } from '@/lib/approvalText';

interface SignoffEntry {
  user_id: string;
  user_email: string;
  user_name?: string | null;
  decision: 'approve' | 'deny' | 'return';
  reason: string;
  at: string;
  sole_operator?: boolean;
}

interface ApprovalRow {
  id: string;
  agent_id: string | null;
  agent_execution_id: string | null;
  title: string;
  payload: Record<string, unknown>;
  required_signoffs: number;
  signoffs: SignoffEntry[];
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'returned' | 'withdrawn';
  requested_by: string | null;
  expires_at: string | null;
  decided_at: string | null;
  created_at: string | null;
  gate_kind?: string | null;
  policy?: { exclude_requester?: boolean; capability?: string } | null;
  self_approved?: boolean;
  eligible_approver_count?: number | null;
  sole_operator_available?: boolean;
  can_sign?: boolean;
  cannot_sign_reason?: string | null;
  requested_by_name?: string | null;
  change_note?: string | null;
  changes?: number | null;
  kind_label?: string | null;
  summary?: string | null;
  agent_name?: string | null;
  run_label?: string | null;
  withdraw_reason?: string | null;
  withdrawn_by_name?: string | null;
  eligible_approvers?: { id: string; name: string }[] | null;
}

// rule changes and tier changes can be signed by the requester alone when nobody else can
const SOLE_KINDS = new Set(['decision_publish', 'decision_tier_change', 'decision_reattest', 'decision_retire', 'decision_archive', 'decision_restore']);
const DECISION_KINDS = SOLE_KINDS;

const GATE_KIND_LABEL: Record<string, string> = {
  human_approval: 'agent gate',
  decision_publish: 'rule change',
  decision_tier_change: 'risk tier change',
  decision_reattest: 'review after a tier raise',
  decision_retire: 'retire a decision version',
  decision_archive: 'archive a decision',
  decision_restore: 'restore a decision',
  'autonomy.promote': 'promotion',
  'improvement.release': 'agent improvement',
};

function gateLabel(kind: string, label?: string | null): string {
  if (label) return label;
  if (isActionGate(kind)) return 'agent action';
  // an app's own kind, such as gw.plan.change, reads as plan change
  return GATE_KIND_LABEL[kind] || kind.split('.').filter(Boolean).slice(-2).join(' ').replace(/_/g, ' ');
}

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  approved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  denied: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  expired: 'bg-slate-500/15 text-slate-400 border-slate-500/40',
  returned: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  withdrawn: 'bg-slate-500/15 text-slate-300 border-slate-500/40',
};

const STATUS_TEXT: Record<string, string> = {
  pending: 'Pending', approved: 'Approved', denied: 'Denied', expired: 'Expired', returned: 'Returned', withdrawn: 'Withdrawn',
};

function PayloadView({ payload }: { payload: unknown }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!payload || typeof payload !== 'object') {
    return (
      <pre className="text-[11px] text-slate-300 bg-slate-900/60 border border-slate-800 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words max-h-56">
        {JSON.stringify(payload, null, 2)}
      </pre>
    );
  }
  const entries = Object.entries(payload as Record<string, unknown>);
  if (entries.length === 0) {
    return <p className="text-[11px] text-slate-400 italic">Empty payload.</p>;
  }
  return (
    <div className="space-y-1.5" data-testid="approval-payload-view">
      {entries.map(([key, value]) => (
        <PayloadRow key={key} k={key} v={value} depth={0} />
      ))}
      <button
        type="button"
        onClick={() => setShowRaw((v) => !v)}
        className="mt-2 text-[10px] text-slate-400 hover:text-slate-200"
      >
        {showRaw ? 'Hide raw JSON' : 'Show raw JSON'}
      </button>
      {showRaw && (
        <pre className="text-[10px] text-slate-400 bg-slate-900/40 border border-slate-800/70 rounded p-2 overflow-x-auto whitespace-pre-wrap break-words max-h-48 mt-1">
          {JSON.stringify(payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

function PayloadRow({ k, v, depth }: { k: string; v: unknown; depth: number }) {
  const label = k.replace(/_/g, ' ');
  if (v === null || v === undefined) {
    return (
      <div className="flex items-baseline gap-2 text-[11px]" style={{ paddingLeft: depth * 12 }}>
        <span className="text-slate-500 uppercase tracking-wide text-[10px] min-w-[120px]">{label}</span>
        <span className="text-slate-600 italic">—</span>
      </div>
    );
  }
  if (typeof v === 'object' && !Array.isArray(v)) {
    const entries = Object.entries(v as Record<string, unknown>);
    return (
      <div style={{ paddingLeft: depth * 12 }}>
        <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1 mt-1">{label}</p>
        <div className="space-y-1">
          {entries.map(([k2, v2]) => (
            <PayloadRow key={k2} k={k2} v={v2} depth={depth + 1} />
          ))}
        </div>
      </div>
    );
  }
  if (Array.isArray(v)) {
    return (
      <div style={{ paddingLeft: depth * 12 }}>
        <p className="text-[10px] uppercase tracking-wide text-slate-400 mb-1 mt-1">{label} <span className="text-slate-500 normal-case">({v.length} item{v.length === 1 ? '' : 's'})</span></p>
        <div className="space-y-1">
          {v.slice(0, 8).map((item, idx) => (
            <PayloadRow key={idx} k={`#${idx}`} v={item} depth={depth + 1} />
          ))}
          {v.length > 8 && (
            <p className="text-[10px] text-slate-600 italic" style={{ paddingLeft: (depth + 1) * 12 }}>
              {v.length - 8} more…
            </p>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-baseline gap-2 text-[11px]" style={{ paddingLeft: depth * 12 }}>
      <span className="text-slate-500 uppercase tracking-wide text-[10px] min-w-[120px]">{label}</span>
      <span className="text-slate-200 font-mono break-words">{String(v)}</span>
    </div>
  );
}

function relTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso).getTime();
  const diff = Math.max(0, Date.now() - d);
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function expiryString(iso: string | null, nowMs: number): string {
  if (!iso) return '';
  const target = new Date(iso).getTime();
  const remaining = target - nowMs;
  if (remaining <= 0) return 'expired';
  if (remaining < 60_000) return `${Math.ceil(remaining / 1000)}s left`;
  const m = Math.floor(remaining / 60000);
  if (m < 60) return `${m}m left`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h left`;
  return `${Math.floor(h / 24)}d left`;
}

function useLiveClock(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

function ApprovalCard({ row, onDecide, busy, meId, isAdmin, onReload }: { row: ApprovalRow; onDecide: (id: string, decision: 'approve' | 'deny' | 'return', reason?: string) => Promise<string | null>; busy: boolean; meId?: string; isAdmin?: boolean; onReload?: () => void }) {
  const [open, setOpen] = useState(false);
  const [sole, setSole] = useState(false);
  const [soleDone, setSoleDone] = useState(false);
  const [reason, setReason] = useState('');
  const [decideErr, setDecideErr] = useState<string | null>(null);
  const [denying, setDenying] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const confirm = takesOutOfService(row) ? confirmApproveText(row) : null;
  async function decide(d: 'approve' | 'deny' | 'return', sure = false) {
    setDecideErr(null);
    if (d === 'deny') { setDenying(true); return; }
    if (d === 'approve' && confirm && !sure) { setConfirming(true); return; }
    setConfirming(false);
    if (d === 'return' && !reason.trim()) {
      setOpen(true);
      setDecideErr('Say what needs to change in the reason box, then press Return again.');
      return;
    }
    const e = await onDecide(row.id, d, reason);
    if (e) setDecideErr(e);
  }
  const isPending = row.status === 'pending';
  const approveCount = row.signoffs.filter(s => s.decision === 'approve').length;
  // the person who asked can't sign their own rule change, so don't offer a button that will fail
  const mine = !!meId && !!row.requested_by && String(row.requested_by) === String(meId);
  const blockedAsAuthor = isPending && mine && !!row.gate_kind && SOLE_KINDS.has(row.gate_kind) && row.policy?.exclude_requester !== false;
  const others = row.eligible_approver_count ?? null;
  const cannotSign = isPending && !blockedAsAuthor && row.can_sign === false;
  const soleSign = row.signoffs.find((s) => s.sole_operator);
  const now = useLiveClock(isPending && row.expires_at ? 1000 : 60_000);
  // the names of who can sign a rule change come from the decision itself
  const dk = row.payload?.decision_key;
  const dv = row.payload?.version;
  const { data: who } = useApi<{ eligible_approvers: { id: string; name: string; email: string }[] }>(
    blockedAsAuthor && others && (row.gate_kind === 'decision_publish' || row.gate_kind === 'decision_reattest') && typeof dk === 'string' && dv !== undefined
      ? `/api/decisions/${encodeURIComponent(dk)}/versions/${encodeURIComponent(String(dv))}/sign-off`
      : null,
  );
  // the row names who can sign since 2.5.7, the sign-off lookup covers older rows
  const otherNames = (row.eligible_approvers?.length ? row.eligible_approvers : who?.eligible_approvers || []).map((p) => p.name || ('email' in p ? (p as { email?: string }).email : '') || 'someone');
  const refused = refusal(row);
  const askedBy = requesterName(row);
  const because = askedBecause(row);

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 mb-3" data-testid="approval-card" data-approval-id={row.id} data-status={row.status}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-[240px]">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <ShieldCheck className="w-4 h-4 text-cyan-400 shrink-0" />
            <h3 className="text-sm font-semibold text-white min-w-0 break-words">{row.title || 'Approval requested'}</h3>
            <span className={`text-[10px] px-2 py-0.5 rounded-full border uppercase tracking-wider ${STATUS_BADGE[row.status]}`}>
              {STATUS_TEXT[row.status] || row.status}
            </span>
            {row.self_approved && (soleSign ? <SelfApprovedBadge name={soleSign.user_email} /> : (
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-amber-500/40 text-amber-200" data-testid="approval-own-signoff">signed by the person who asked</span>
            ))}
            {row.gate_kind && (
              <span
                className="text-[10px] px-2 py-0.5 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 tracking-wide"
                data-testid="approval-gate-kind"
                title={row.gate_kind}
              >
                {gateLabel(row.gate_kind, row.kind_label)}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-3 text-[11px] text-slate-500">
            <span data-testid="approval-requester">Asked{askedBy ? ` by ${askedBy}` : ''} {relTime(row.created_at)}</span>
            <span>{approveCount}/{row.required_signoffs} approvals</span>
            {row.expires_at && row.status === 'pending' && (
              <span className="text-amber-300/80 flex items-center gap-1" data-testid="approval-expiry">
                <Clock className="w-3 h-3" /> {expiryString(row.expires_at, now)}
              </span>
            )}
            {row.agent_execution_id && (
              <Link href={`/executions/${encodeURIComponent(row.agent_execution_id)}`} className="text-cyan-300/80 hover:underline" data-testid="approval-run-link">{row.run_label || 'Open the run'}</Link>
            )}
          </div>
          {refused && (
            <p className={`mt-1.5 rounded-md border px-2.5 py-1.5 text-xs ${refused.verb === 'Denied' ? 'border-rose-500/40 bg-rose-500/10 text-rose-100' : 'border-amber-500/40 bg-amber-500/10 text-amber-100'}`} data-testid="approval-refusal">
              <span className="font-semibold">{refused.verb} by {refused.by}</span>{refused.reason ? `: “${refused.reason}”` : '. No reason was given.'}
            </p>
          )}
          {row.gate_kind === 'autonomy.promote' && <PromotionSummary payload={row.payload} />}
          {row.gate_kind === 'decision_publish' && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]" data-testid="approval-decision">
              {typeof row.payload?.link === 'string' && (
                <a href={row.payload.link as string} className="text-cyan-300 hover:underline">Review the rules and what changes</a>
              )}
              {typeof row.payload?.summary === 'string' && <span className="text-slate-400">{tidySummary(row.payload.summary as string)}</span>}
              {changesText(row) && <span className="text-slate-400" data-testid="approval-changes">{changesText(row)}</span>}
              {isPending && (
                <span className="text-slate-500">
                  Anyone in Decision reviewers can approve it{row.policy?.exclude_requester ? ', except the person who proposed it' : ''}.
                </span>
              )}
            </div>
          )}
          {(row.gate_kind === 'decision_retire' || row.gate_kind === 'decision_archive' || row.gate_kind === 'decision_restore') && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]" data-testid="approval-lifecycle">
              <span className="text-slate-300">
                {row.gate_kind === 'decision_retire' ? `Retire version ${String(row.payload?.version ?? '?')} of ${String(row.payload?.decision_key ?? 'a decision')}` : row.gate_kind === 'decision_archive' ? `Archive ${String(row.payload?.decision_key ?? 'a decision')}` : `Restore ${String(row.payload?.decision_key ?? 'a decision')}`}, at {tierName(String(row.payload?.tier ?? 'its'))} risk.
              </span>
              {typeof row.payload?.link === 'string' && <a href={row.payload.link as string} className="text-cyan-300 hover:underline">Open the decision</a>}
            </div>
          )}
          {!row.gate_kind || !(DECISION_KINDS.has(row.gate_kind) || row.gate_kind === 'autonomy.promote') ? <GenericSummary payload={row.payload} summary={row.summary} /> : null}
          {isPending && !blockedAsAuthor && decisionEffect(row, 'before') && <p className="mt-1.5 text-[11px] text-slate-400" data-testid="approval-effect">{decisionEffect(row, 'before')}</p>}
          {row.gate_kind === 'decision_tier_change' && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]" data-testid="approval-tier-change">
              <span className="text-slate-300">
                Lower {String(row.payload?.decision_key ?? 'the decision')} from {tierName(String(row.payload?.from_tier ?? '?'))} to {tierName(String(row.payload?.to_tier ?? '?'))} risk.
              </span>
              {typeof row.payload?.link === 'string' && <a href={row.payload.link as string} className="text-cyan-300 hover:underline">Open the decision</a>}
              {isPending && <span className="text-slate-500">Needs sign-off at the current tier, from someone other than the person who asked.</span>}
            </div>
          )}
          {row.self_approved && soleSign?.reason && <p className="mt-1.5 text-[11px] text-amber-200/90" data-testid="approval-self-reason">Their reason: “{soleSign.reason}”</p>}
          {row.gate_kind === 'decision_reattest' && (
            <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]" data-testid="approval-reattest">
              <span className="text-slate-300">
                {String(row.payload?.decision_key ?? 'The decision')} version {String(row.payload?.version ?? '?')} is in force but was approved under {tierName(String(row.payload?.from_tier ?? '?'))} risk. Review it at {tierName(String(row.payload?.to_tier ?? '?'))} risk.
              </span>
              {typeof row.payload?.link === 'string' && <a href={row.payload.link as string} className="text-cyan-300 hover:underline">Review the rules</a>}
              <span className="text-slate-500">The version keeps answering while this waits.</span>
            </div>
          )}
          {because && DECISION_KINDS.has(row.gate_kind || '') && (
            <p className="mt-1 text-[11px] text-slate-300" data-testid="approval-because">
              <span className="text-slate-500">{row.gate_kind === 'decision_publish' || row.gate_kind === 'decision_reattest' ? 'What changed and why: ' : 'Asked because: '}</span>“{because}”
            </p>
          )}
          {row.status === 'withdrawn' && (
            <p className="mt-1.5 text-[11px] text-slate-400" data-testid="approval-withdrawn">
              {withdrawnText(row)}
            </p>
          )}
          {blockedAsAuthor && (
            <div className="mt-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-[11px] text-slate-300 space-y-1" data-testid="approval-author-note">
              <p>You asked for this, so you can&apos;t approve it yourself.</p>
              {others ? (
                <p className="text-slate-400" data-testid="approval-who-can">
                  {otherNames.length ? `Who can approve it: ${otherNames.slice(0, 4).join(', ')}${otherNames.length > 4 ? ` and ${otherNames.length - 4} more` : ''}.` : others === 1 ? 'One other person can approve it.' : `${others} other people can approve it.`} Ask one of them, they see it in Needs you.
                </p>
              ) : row.sole_operator_available ? (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-amber-200">Nobody else in this workspace can approve it, so you can sign it off yourself with a written reason.</span>
                  {!soleDone && (
                    <button type="button" onClick={() => setSole(true)} className="px-2.5 py-1 rounded-md border border-amber-500/50 text-amber-200 hover:bg-amber-500/10" data-testid="approval-sole-open">
                      Approve as the only approver
                    </button>
                  )}
                </div>
              ) : (
                <p className="text-amber-200">Nobody else in this workspace can approve it yet. <InviteApprover isAdmin={!!isAdmin} decisionKey={typeof row.payload?.decision_key === 'string' ? row.payload.decision_key : null} /></p>
              )}
            </div>
          )}
        </div>
        {cannotSign && (
          <p className="basis-full text-[11px] text-slate-300 rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2" data-testid="approval-cannot-sign">
            {row.cannot_sign_reason || 'You can see this request, but someone else has to approve it.'}
          </p>
        )}
        {isPending && !blockedAsAuthor && !cannotSign && (
          <div className="flex flex-col sm:flex-row gap-2 shrink-0 w-full sm:w-auto">
            <button
              disabled={busy}
              onClick={() => decide('approve')}
              className="px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs font-medium hover:bg-emerald-500/25 disabled:opacity-50 flex items-center gap-1.5 justify-center"
              data-testid="approval-approve"
            >
              <CheckCircle2 className="w-3.5 h-3.5" /> Approve
            </button>
            <button
              disabled={busy}
              onClick={() => decide('deny')}
              className="px-3 py-1.5 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs font-medium hover:bg-rose-500/25 disabled:opacity-50 flex items-center gap-1.5 justify-center"
              data-testid="approval-deny"
            >
              <XCircle className="w-3.5 h-3.5" /> Deny
            </button>
            {!row.id.startsWith('hitl:') && (
              <button
                disabled={busy}
                onClick={() => decide('return')}
                className="px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/40 text-amber-300 text-xs font-medium hover:bg-amber-500/20 disabled:opacity-50 flex items-center gap-1.5 justify-center"
                data-testid="approval-return"
              >
                Return for changes
              </button>
            )}
          </div>
        )}
        {decideErr && <p className="basis-full text-xs text-rose-300" role="alert" data-testid="approval-error">{decideErr}</p>}
      </div>
      <button
        onClick={() => setOpen(o => !o)}
        className="mt-3 flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-white"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Details and sign-off history
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Payload</p>
            <PayloadView payload={row.payload} />
          </div>
          {row.signoffs.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Signoffs</p>
              <div className="space-y-1">
                {row.signoffs.map((s, idx) => (
                  <div key={idx} className="flex flex-wrap items-center gap-2 text-[11px] bg-slate-900/40 border border-slate-800 rounded-md px-2 py-1.5">
                    {s.decision === 'approve' ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    ) : (
                      <XCircle className="w-3.5 h-3.5 text-rose-400" />
                    )}
                    <span className="text-white font-medium">{signerName(s)}</span>
                    <span className="text-slate-500">{s.decision === 'approve' ? 'approved' : s.decision === 'deny' ? 'denied' : 'sent it back'}</span>
                    {s.sole_operator && <span className="text-[10px] px-1.5 rounded border border-amber-500/40 text-amber-200">only approver</span>}
                    {s.reason && <span className="text-slate-400 italic truncate max-w-xs">"{s.reason}"</span>}
                    <span className="text-slate-600 ml-auto">{relTime(s.at)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {isPending && !blockedAsAuthor && (
            <div>
              <label className="text-[10px] uppercase tracking-wider text-slate-500">Reason (needed to return it)</label>
              <input
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="Why are you approving, denying or returning it?"
                className="mt-1 w-full px-2 py-1.5 text-[11px] bg-slate-900/60 border border-slate-700 rounded-md text-white placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
              />
            </div>
          )}
        </div>
      )}
      {confirm && (
        <ConfirmModal
          open={confirming}
          onClose={() => setConfirming(false)}
          onConfirm={() => decide('approve', true)}
          title={confirm.title}
          description={confirm.body}
          confirmLabel="Approve"
          variant="warning"
          confirmTestId="approval-approve-confirm"
        />
      )}
      {denying && (
        <ReasonDialog
          title="Deny this request?"
          intro={`${row.title || 'This request'} will not go ahead. Say why, so the person who asked knows what to change.`}
          verb="Deny"
          placeholder="what is wrong, or what would make it acceptable"
          testId="deny-dialog"
          onClose={() => setDenying(false)}
          onConfirm={async (why) => { const e = await onDecide(row.id, 'deny', why); if (!e) setDenying(false); return e; }}
        />
      )}
      {sole && (
        <SoleOperatorDialog
          approvalId={row.id}
          title={row.title || 'Approval requested'}
          onClose={() => setSole(false)}
          onDone={() => { setSole(false); setSoleDone(true); onReload?.(); }}
        />
      )}
    </div>
  );
}

// "1 golden test pass" reads wrong, the rest of the summary is kept as written
function tidySummary(t: string): string {
  return t.replace(/\b1 golden test pass\b/, '1 golden test passes');
}

// the real reason a request was taken back, and by whom when a person did it
function withdrawnText(row: ApprovalRow): string {
  const why = (row.withdraw_reason || (typeof row.payload?.withdrawn === 'string' ? row.payload.withdrawn : '') || '').trim();
  const by = row.withdrawn_by_name ? ` by ${row.withdrawn_by_name}` : '';
  if (!why) return 'The person who asked withdrew it. Nothing changed.';
  return `Withdrawn${by}. ${why.replace(/\.?$/, '.')} Nothing else changed.`;
}

// every request says what it is about, even when whoever raised it sent little
function GenericSummary({ payload, summary }: { payload: Record<string, unknown>; summary?: string | null }) {
  const p = payload || {};
  const text = (summary && summary.trim()) || (['summary', 'details', 'description', 'reason', 'message'].map((k) => p[k]).find((v) => typeof v === 'string' && v.trim()) as string | undefined);
  return (
    <p className={`mt-1.5 text-[11px] ${text ? 'text-slate-300' : 'text-amber-200/90'}`} data-testid="approval-summary">
      {text || 'No details were sent with this request. Open the payload below, or ask whoever raised it, before you approve.'}
    </p>
  );
}

function PromotionSummary({ payload }: { payload: Record<string, unknown> }) {
  // the API sends grant_id with agent and action_type beside it, older rows nest them in grant
  const g = payload?.grant as { id?: string; agent?: { name?: string }; action_type?: { label?: string } } | string | undefined;
  const nested = typeof g === 'object' ? g : undefined;
  const grantId = (typeof payload?.grant_id === 'string' ? payload.grant_id : undefined) || (typeof g === 'string' ? g : nested?.id);
  const agentName = (payload?.agent as { name?: string } | undefined)?.name || nested?.agent?.name;
  const actionLabel = (payload?.action_type as { label?: string } | undefined)?.label || nested?.action_type?.label;
  const from = typeof payload?.from === 'number' ? payload.from : null;
  const to = typeof payload?.to === 'number' ? payload.to : null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px]" data-testid="approval-promotion">
      <span className="text-slate-300">
        {agentName ? `${agentName}, ` : ''}{actionLabel ? `${actionLabel}: ` : ''}
        {from !== null && to !== null ? `${levelLabel(from)} to ${levelLabel(to)}` : 'move up a level'}
      </span>
      {grantId && <Link href={`/autonomy/${encodeURIComponent(grantId)}`} className="text-cyan-300 hover:underline">See the evidence</Link>}
      {typeof payload?.self_approval === 'string' ? (
        <span className="text-cyan-200" data-testid="approval-self-approval">{payload.self_approval}</span>
      ) : (
        <span className="text-slate-500">Needs autonomy.grant, and not the person who built the agent</span>
      )}
    </div>
  );
}

export default function ApprovalsPage() {
  const { perms } = useMyPermissions();
  const { user: me } = useAuth();
  const canReview = holds(perms?.capabilities, 'actions.review');
  const [tab, setTab] = useState<'pending' | 'reviews'>('pending');
  const [reviewCount, setReviewCount] = useState<number | null>(null);

  useEffect(() => {
    try {
      const t = new URLSearchParams(window.location.search).get('tab');
      if (t === 'reviews' || t === 'watching') setTab('reviews');
    } catch { /* no window in tests */ }
  }, []);

  const switchTab = (t: 'pending' | 'reviews') => {
    setTab(t);
    try {
      const url = new URL(window.location.href);
      if (t === 'reviews') url.searchParams.set('tab', 'reviews');
      else url.searchParams.delete('tab');
      window.history.replaceState(null, '', url.toString());
    } catch { /* ignore */ }
  };

  const [pending, setPending] = useState<ApprovalRow[]>([]);
  const [recent, setRecent] = useState<ApprovalRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [released, setReleased] = useState<Decided | null>(null);
  const [decided, setDecided] = useState<{ text: string; link: string | null } | null>(null);
  // admins can look at everything, everyone else sees what they can sign and their own requests
  const [showAll, setShowAll] = useState(false);
  const showAllRef = useRef(false);
  showAllRef.current = showAll;
  // an edited fix leaves the list while it is proved again, its card stays to say so
  const [held, setHeld] = useState<Record<string, ApprovalRow>>({});
  const [recentShown, setRecentShown] = useState(20);
  const [recentMore, setRecentMore] = useState(false);
  const [recentTotal, setRecentTotal] = useState<number | null>(null);
  const recentLimitRef = useRef(20);

  const load = useCallback(async () => {
    const scope = showAllRef.current ? '&all=1' : '';
    const pendingRes = await apiFetch<ApprovalRow[]>(`/api/approvals?mine=1&status=pending${scope}`, { silent: true });
    const recentRes = await apiFetch<ApprovalRow[]>(`/api/approvals?mine=1${scope}&status=resolved&offset=0&limit=${recentLimitRef.current}`, { silent: true });
    if (pendingRes.error && !pendingRes.data) {
      setError(pendingRes.error);
    } else {
      setError(null);
      setPending(pendingRes.data || []);
    }
    const all = recentRes.data || [];
    setRecent(all.filter(a => a.status !== 'pending'));
    setRecentMore(!!recentRes.meta?.has_more);
    setRecentTotal(typeof recentRes.meta?.total === 'number' ? (recentRes.meta.total as number) : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const onImprovementDecided = (d: Decided, row: ApprovalRow) => {
    if (d.decision === 'edit') {
      const withdrawn = 'The fix was edited, so it is being proved again.';
      setHeld((h) => ({ ...h, [row.id]: { ...row, status: 'expired', payload: { ...row.payload, withdrawn } } }));
    }
    setReleased(d);
    load();
  };

  useEffect(() => {
    const back = (r: ApprovalRow) =>
      pending.some((p) => p.id !== r.id && p.payload?.proposal_id && p.payload.proposal_id === r.payload?.proposal_id);
    setHeld((h) => {
      const keep = Object.fromEntries(Object.entries(h).filter(([, r]) => !back(r)));
      return Object.keys(keep).length === Object.keys(h).length ? h : keep;
    });
  }, [pending]);

  const shown = [...pending, ...Object.values(held).filter((r) => !pending.some((p) => p.id === r.id))];
  const isMine = (a: ApprovalRow) => !!me?.id && !!a.requested_by && String(a.requested_by) === String(me.id);
  const toSign = shown.filter((a) => a.can_sign !== false && !(isMine(a) && a.can_sign === undefined && a.gate_kind && SOLE_KINDS.has(a.gate_kind)));
  const yours = shown.filter((a) => !toSign.includes(a) && isMine(a));
  const others = shown.filter((a) => !toSign.includes(a) && !yours.includes(a));
  const pendingLabel = [toSign.length ? `${toSign.length} to sign` : '', yours.length ? `${yours.length} yours` : ''].filter(Boolean).join(' · ');

  // links like /approvals#<id> open on that approval
  const [jumped, setJumped] = useState(false);
  useEffect(() => {
    if (jumped || loading) return;
    const id = typeof window !== 'undefined' ? decodeURIComponent(window.location.hash.slice(1)) : '';
    if (!id) return;
    const el = document.querySelector(`[data-approval-id="${CSS.escape(id)}"]`) as HTMLElement | null;
    if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('ring-2', 'ring-cyan-500/60'); setJumped(true); }
  }, [jumped, loading, pending, recent]);

  const handleDecide = async (
    id: string,
    decision: 'approve' | 'deny' | 'return',
    reason?: string,
    editedArguments?: Record<string, unknown>,
  ): Promise<string | null> => {
    setBusyId(id);
    const row = pending.find((p) => p.id === id);
    // ids are opaque strings, agent gates look like hitl:{execution}:{gate}
    const r = await signoffApproval(id, decision, reason, editedArguments);
    setBusyId(null);
    await load();
    if (!r.error && row) {
      const next = decisionEffect(row, 'after', decision);
      if (next) setDecided({ text: `${row.title ? `${row.title}: ` : ''}${next}`, link: typeof row.payload?.link === 'string' ? (row.payload.link as string) : null });
    }
    return r.error ? signoffError(r.code, decisionErrorText(r.code, r.error, r.details), reason) : null;
  };

  const renderRow = (a: ApprovalRow) => (
    a.gate_kind === 'improvement.release'
      ? <ImprovementApprovalCard key={a.id} approval={a as unknown as Record<string, unknown>} onDecided={(d) => onImprovementDecided(d, a)} />
      : isActionGate(a.gate_kind)
      ? <ApprovalActionRow key={a.id} row={a} onDecide={handleDecide} busy={busyId === a.id} />
      : <ApprovalCard key={a.id} row={a} onDecide={handleDecide} busy={busyId === a.id} meId={me?.id} isAdmin={!!perms?.is_admin} onReload={load} />
  );

  return (
    <div className="max-w-5xl mx-auto">
      <PageHeader
        className="mb-6"
        title="Approvals"
        purpose="Sign off on agent actions, rule changes, promotions and proven agent fixes that need a person before they happen. For approvers and reviewers."
        icon={ShieldCheck}
        storageKey="approvals"
        docSlug="02-runtime/05-approvals-hitl"
        primaryAction={{ label: 'Everything that needs you', href: '/inbox', icon: Inbox }}
        secondaryAction={{ label: 'Refresh', onClick: load, icon: RefreshCw, busy: loading, testId: 'approvals-refresh' }}
        steps={[
          'To sign lists the requests waiting on you. Your own requests sit below it so you can follow them. It refreshes by itself every five seconds.',
          'Open one to see what it changes and why, then approve, deny with a reason, or send it back.',
          'Watching reviews is where you agree or disagree with agents that are still earning autonomy.',
        ]}
      />

      <div className="mb-5 flex gap-1 border-b border-slate-800" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'pending'}
          onClick={() => switchTab('pending')}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === 'pending' ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`}
          data-testid="approvals-tab-pending"
        >
          Pending approvals{pendingLabel ? ` (${pendingLabel})` : ''}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'reviews'}
          onClick={() => switchTab('reviews')}
          className={`-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm ${tab === 'reviews' ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'}`}
          data-testid="approvals-tab-reviews"
        >
          <Eye className="h-3.5 w-3.5" /> Watching reviews{reviewCount ? ` (${reviewCount})` : ''}
        </button>
      </div>

      {tab === 'reviews' ? (
        <ReviewQueue canReview={canReview} onCountChange={setReviewCount} />
      ) : (
      <>
      {error && (
        <div className="mb-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 flex items-center gap-2 text-sm text-rose-200">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <ReleasedNext decided={released} onDismiss={() => setReleased(null)} />
      {decided && (
        <div className="mb-4 flex items-start gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100" role="status" data-testid="approval-decided">
          <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="flex-1">{decided.text}</span>
          {decided.link && <Link href={decided.link} className="text-xs text-cyan-200 underline hover:text-white" data-testid="approval-decided-open">Open the decision</Link>}
          <button type="button" onClick={() => setDecided(null)} className="text-xs text-emerald-200 hover:text-white">Dismiss</button>
        </div>
      )}

      {perms && !perms.is_admin && !perms.can_approve_decisions && (
        <ViewOnlyBanner testId="approvals-view-only">
          {holds(perms.capabilities, 'approvals.sign')
            ? 'You can sign agent actions here, but not rule changes. Rule changes are signed by people in Decision reviewers. Ask an admin to tick Can approve decisions for you on Team.'
            : 'You can follow your own requests here. Rule changes are signed by people in Decision reviewers and agent actions by people with Sign approvals. Ask an admin to tick Can approve decisions for you on Team.'}
        </ViewOnlyBanner>
      )}

      <section className="mb-8" data-testid="approvals-to-sign">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white uppercase tracking-wider">To sign</h2>
          {perms?.is_admin && (
            <label className="ml-auto mr-3 inline-flex items-center gap-1.5 text-[11px] text-slate-400" title="Also show requests you can't sign">
              <input type="checkbox" checked={showAll} onChange={(e) => { setShowAll(e.target.checked); showAllRef.current = e.target.checked; load(); }} className="accent-cyan-500" data-testid="approvals-show-all" />
              Show everyone&apos;s
            </label>
          )}
          <span className="text-[11px] text-slate-400" data-testid="approvals-to-sign-count">{toSign.length} waiting on you</span>
        </div>
        {loading && pending.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-8 justify-center">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading approvals
          </div>
        ) : toSign.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center">
            <CheckCircle2 className="w-8 h-8 text-emerald-400/40 mx-auto mb-2" />
            <p className="text-sm text-slate-400">Nothing waiting on you right now. Requests you can sign show up here{yours.length ? ', yours are listed below' : ''}.</p>
          </div>
        ) : (
          toSign.map(renderRow)
        )}
      </section>

      {yours.length > 0 && (
        <section className="mb-8" data-testid="approvals-yours">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider">Your requests, waiting on someone else</h2>
            <span className="text-[11px] text-slate-400">{yours.length} waiting</span>
          </div>
          {yours.map(renderRow)}
        </section>
      )}

      {others.length > 0 && (
        <section className="mb-8" data-testid="approvals-others">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-white uppercase tracking-wider">Everyone else&apos;s</h2>
            <span className="text-[11px] text-slate-400">{others.length} you can&apos;t sign</span>
          </div>
          {others.map(renderRow)}
        </section>
      )}

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-white uppercase tracking-wider">Recently resolved</h2>
          <span className="text-[11px] text-slate-400" data-testid="approvals-resolved-count">{`Showing ${Math.min(recentShown, recent.length)} of ${recentTotal ?? `${recent.length}${recentMore ? '+' : ''}`}`}</span>
        </div>
        {recent.length === 0 ? (
          <p className="text-xs text-slate-500">Nothing resolved yet.</p>
        ) : (
          recent.slice(0, recentShown).map(a => (
            a.gate_kind === 'improvement.release'
              ? <ImprovementApprovalCard key={a.id} approval={a as unknown as Record<string, unknown>} onDecided={(d) => onImprovementDecided(d, a)} />
              : isActionGate(a.gate_kind)
              ? <ApprovalActionRow key={a.id} row={a} onDecide={handleDecide} busy={busyId === a.id} />
              : <ApprovalCard key={a.id} row={a} onDecide={handleDecide} busy={busyId === a.id} meId={me?.id} isAdmin={!!perms?.is_admin} onReload={load} />
          ))
        )}
        {(recent.length > recentShown || recentMore) && (
          <button
            type="button"
            onClick={() => {
              if (recent.length > recentShown) setRecentShown((n) => n + 20);
              else { recentLimitRef.current = Math.min(500, recentLimitRef.current + 20); setRecentShown((n) => n + 20); load(); }
            }}
            className="mt-2 w-full rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800"
            data-testid="approvals-show-more"
          >
            Show more
          </button>
        )}
      </section>
      </>
      )}
    </div>
  );
}
