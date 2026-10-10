import { tidySummary } from '@/lib/decisionValues';

export interface ApprovalSignoff {
  user_id?: string;
  user_email?: string;
  user_name?: string | null;
  decision?: string;
  reason?: string;
  at?: string;
  sole_operator?: boolean;
}

export interface ApprovalLike {
  id: string;
  title?: string;
  status?: string;
  gate_kind?: string | null;
  payload?: Record<string, unknown>;
  policy?: { risk_tier?: string; exclude_requester?: boolean } | null;
  signoffs?: ApprovalSignoff[];
  requested_by?: string | null;
  requested_by_name?: string | null;
  change_note?: string | null;
  changes?: number | null;
}

export const MIN_DENY_REASON = 5;

const cap = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

export const LIFECYCLE_KINDS = new Set(['decision_retire', 'decision_archive', 'decision_restore']);

export const GATE_LABEL: Record<string, string> = {
  human_approval: 'Agent gate',
  decision_publish: 'Rule change',
  decision_tier_change: 'Risk tier change',
  decision_reattest: 'Review after a tier raise',
  decision_retire: 'Retire a version',
  decision_archive: 'Archive a decision',
  decision_restore: 'Restore a decision',
  'autonomy.promote': 'Promotion',
  'improvement.release': 'Agent improvement',
};

function str(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v.trim() : null;
}

export function tierOf(row: ApprovalLike): string | null {
  const p = row.payload || {};
  return str(p.tier) || str(p.risk_tier) || str(row.policy?.risk_tier) || null;
}

export function decisionLink(row: ApprovalLike): string | null {
  const p = row.payload || {};
  return str(p.link) || (str(p.decision_key) ? `/decisions/${encodeURIComponent(String(p.decision_key))}` : null);
}

// "Retire version 1 of site.exclusion, at high risk."
export function lifecycleLine(row: ApprovalLike): string | null {
  if (!row.gate_kind || !LIFECYCLE_KINDS.has(row.gate_kind)) return null;
  const p = row.payload || {};
  const key = str(p.decision_key) || 'a decision';
  const tier = tierOf(row);
  const at = tier ? `, at ${cap(tier)} risk` : '';
  if (row.gate_kind === 'decision_retire') return `Retire version ${String(p.version ?? '?')} of ${key}${at}. It stops answering.`;
  if (row.gate_kind === 'decision_archive') return `Archive ${key}${at}. It leaves the list and stops answering.`;
  return `Restore ${key}${at}. It comes back and answers again if a version is in force.`;
}

// approving takes a rule out of service, so a High or Critical one asks twice
export function takesOutOfService(row: ApprovalLike): boolean {
  if (row.gate_kind !== 'decision_retire' && row.gate_kind !== 'decision_archive') return false;
  const t = tierOf(row);
  return t === 'high' || t === 'critical';
}

// approvals that change something the moment they are signed ask once more
export function needsApproveConfirm(row: ApprovalLike): boolean {
  return takesOutOfService(row) || row.gate_kind === 'decision_tier_change' || row.gate_kind === 'decision_restore';
}


export function confirmApproveText(row: ApprovalLike): { title: string; body: string } {
  const p = row.payload || {};
  const key = str(p.decision_key) || 'this decision';
  const tier = cap(tierOf(row) || 'high');
  const who = requesterName(row) || 'The person who asked';
  if (row.gate_kind === 'decision_tier_change') {
    const from = cap(String(p.from_tier ?? '')), to = cap(String(p.to_tier ?? ''));
    return {
      title: `Lower ${key} from ${from} to ${to} risk?`,
      body: `This takes effect as soon as you approve. Later versions of ${key} then need only the sign-off ${to} risk asks for. ${who} is told.`,
    };
  }
  if (row.gate_kind === 'decision_restore') {
    return {
      title: `Restore ${key}?`,
      body: `It comes back on the list as soon as you approve, and answers agents and apps again if a version is in force. ${who} is told.`,
    };
  }
  if (row.gate_kind === 'decision_retire') {
    return {
      title: `Retire version ${String(p.version ?? '?')} of ${key}?`,
      body: `This is a ${tier} risk decision. Once you approve, that version stops answering at once and agents and apps calling it get no answer from it. It can't be undone from here.`,
    };
  }
  return {
    title: `Archive ${key}?`,
    body: `This is a ${tier} risk decision. Once you approve, it leaves the list and stops answering at once, so agents and apps calling it get no answer. Someone can ask to restore it later.`,
  };
}

export function requesterName(row: ApprovalLike): string | null {
  return str(row.requested_by_name) || str((row.payload || {}).requested_by_name) || null;
}

// what the person who asked wrote, the proposal note for a rule change
export function askedBecause(row: ApprovalLike): string | null {
  const p = row.payload || {};
  if (row.gate_kind === 'decision_publish' || row.gate_kind === 'decision_reattest') return str(row.change_note) || str(p.change_note) || null;
  return str(p.reason);
}

export function changesText(row: ApprovalLike): string | null {
  const n = typeof row.changes === 'number' ? row.changes : typeof row.payload?.changes === 'number' && (row.payload.changes as number) > 0 ? (row.payload.changes as number) : null;
  if (n === null) return null;
  if (n === 0) return 'No rule changes';
  return `${n} rule change${n === 1 ? '' : 's'}`;
}

export function signerName(s: ApprovalSignoff): string {
  return str(s.user_name) || str(s.user_email) || 'Someone';
}

// the reviewer's word on a denied or returned request
export function refusal(row: ApprovalLike): { verb: 'Denied' | 'Sent back'; by: string; reason: string | null } | null {
  if (row.status !== 'denied' && row.status !== 'returned') return null;
  const want = row.status === 'denied' ? 'deny' : 'return';
  const s = [...(row.signoffs || [])].reverse().find((x) => x.decision === want);
  return { verb: row.status === 'denied' ? 'Denied' : 'Sent back', by: s ? signerName(s) : 'a reviewer', reason: s ? str(s.reason) : null };
}

// a REASON_REQUIRED after a reason was typed means it never arrived
export function signoffError(code: string | undefined | null, fallback: string, reason?: string): string {
  if (code === 'REASON_REQUIRED' && (reason || '').trim().length >= MIN_DENY_REASON) return "Couldn't send your reason, try again. If it keeps happening, reload the page.";
  return fallback;
}

export function shortSummary(row: ApprovalLike): string | null {
  const p = row.payload || {};
  const life = lifecycleLine(row);
  if (life) return life;
  if (row.gate_kind === 'decision_tier_change') return `Lower ${String(p.decision_key ?? 'a decision')} from ${cap(String(p.from_tier ?? '?'))} to ${cap(String(p.to_tier ?? '?'))} risk.`;
  if (row.gate_kind === 'decision_reattest') return `${String(p.decision_key ?? 'The decision')} version ${String(p.version ?? '?')} is in force but was approved under ${cap(String(p.from_tier ?? '?'))} risk. Review it at ${cap(String(p.to_tier ?? '?'))} risk.`;
  if (typeof p.summary === 'string' && p.summary) return tidySummary(p.summary);
  if (typeof p.details === 'string' && p.details) return p.details;
  return null;
}

// what approving a rule change does, said before and after
export function approvalEffect(row: { gate_kind?: string | null; payload?: Record<string, unknown> }, when: 'before' | 'after', decision: 'approve' | 'deny' | 'return' = 'approve'): string | null {
  const p = row.payload || {};
  const v = p.version !== undefined ? `version ${String(p.version)}` : 'this version';
  if (row.gate_kind === 'decision_publish') {
    if (when === 'before') return `Approving lets the author publish ${v}. Nothing changes for agents and apps until they do.`;
    if (decision === 'approve') return `Approved. The author is told, and ${v} can be published now from the decision page by anyone with publish rights.`;
    if (decision === 'return') return 'Sent back. The author is told and sees your reason on the decision page.';
    return `Denied. ${v[0].toUpperCase()}${v.slice(1)} cannot be published. The author is told.`;
  }
  if (row.gate_kind === 'decision_tier_change') {
    const to = p.to_tier ? cap(String(p.to_tier)) : 'the lower';
    if (when === 'before') return `Approving moves the decision to ${to} risk straight away, so later versions need less sign-off.`;
    if (decision === 'approve') return `Approved. The decision is now ${to} risk and the person who asked is told.`;
    return 'Nothing changes. The person who asked is told.';
  }
  if (row.gate_kind === 'decision_retire' || row.gate_kind === 'decision_archive' || row.gate_kind === 'decision_restore') {
    const key = String(p.decision_key ?? 'the decision');
    const what = row.gate_kind === 'decision_retire' ? `${v} of ${key} stops answering` : row.gate_kind === 'decision_archive' ? `${key} leaves the list and stops answering` : `${key} comes back and answers again if a version is in force`;
    if (when === 'before') return `Approving means ${what}. Denying leaves everything as it is.`;
    if (decision === 'approve') return `Approved. ${what[0].toUpperCase()}${what.slice(1)}, and the person who asked is told.`;
    return 'Nothing changes. The person who asked is told why.';
  }
  if (row.gate_kind === 'decision_reattest') {
    const to = p.to_tier ? cap(String(p.to_tier)) : 'the new';
    if (when === 'before') return `${v[0].toUpperCase()}${v.slice(1)} keeps answering either way. Approving records that it meets ${to} risk. Denying leaves it as it is, and the author is asked to publish a version signed at ${to} risk or retire it.`;
    if (decision === 'approve') return `Reviewed. ${v[0].toUpperCase()}${v.slice(1)} is recorded as meeting ${to} risk.`;
    return `${v[0].toUpperCase()}${v.slice(1)} keeps answering, and the decision page still asks for the review.`;
  }
  return null;
}
