'use client';

import { useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, BadgeCheck, Loader2, ShieldAlert, UserPlus, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import { tierName, type Tier } from '@/lib/decisions';
import { decisionErrorText } from '@/lib/decisionValues';

export interface SignOffEntry { user_id: string; name: string; at: string; decision?: string; sole_operator: boolean; reason: string | null }

export interface SignOffInfo {
  required: number;
  tier: Tier;
  tier_at_proposal?: Tier | null;
  current_tier?: Tier;
  policy_text: string;
  approval_id: string | null;
  status: 'pending' | 'approved' | 'denied' | 'withdrawn' | 'expired' | 'returned' | null;
  current?: boolean;
  signoffs: SignOffEntry[];
  self_approved?: boolean;
  eligible_approvers: { id: string; name: string; email: string }[];
  author_can_approve: boolean;
  sole_operator_available: boolean;
  // the tier a version in force was last reviewed at, after a raise
  attested_under?: Tier | null;
  attestation?: { approved_by?: string[]; approved_by_names?: string[]; at?: string; self_approved?: boolean } | null;
  // for admins: they can give a teammate the right to approve
  missing_hint?: { can_grant: boolean; permissions_link?: string } | null;
}

interface Member { id: string; email: string; full_name?: string | null; name?: string | null; role?: string; is_active?: boolean }

// an admin adds a teammate to Decision reviewers without leaving the decision
function SomeoneMissing({ decisionKey, eligible, onChanged, authorId }: { decisionKey: string; eligible: { id: string }[]; onChanged: () => void; authorId?: string | null }) {
  const [open, setOpen] = useState(false);
  // the server leaves out removed accounts, the system account and anyone who can already approve
  const { data: cands, error: candErr } = useApi<Member[]>(open ? `/api/decisions/${encodeURIComponent(decisionKey)}/approver-candidates` : null);
  const { data: team } = useApi<{ members: Member[] } | Member[]>(open && candErr ? '/api/team/members' : null);
  const [pick, setPick] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const data = cands ?? team;
  const pool = cands ?? (Array.isArray(team) ? team : team?.members || []).filter((m) => m.is_active !== false && !/@purged\.local$/i.test(m.email || '') && m.role !== 'system');
  const members = pool.filter((m) => !eligible.some((e) => String(e.id) === String(m.id)) && String(m.id) !== String(authorId ?? ''));
  async function give() {
    if (!pick) return;
    setBusy(true);
    const r = await apiFetch(`/api/decisions/${encodeURIComponent(decisionKey)}/approvers`, { method: 'POST', body: JSON.stringify({ user_id: pick }), throwOnError: false });
    setBusy(false);
    const who = members.find((m) => String(m.id) === pick);
    if (r.error) setMsg({ ok: false, text: decisionErrorText(r.errorDetail?.error_code, r.error) });
    else { setMsg({ ok: true, text: `${who?.full_name || who?.name || who?.email || 'They'} can now approve decisions.` }); setPick(''); onChanged(); }
  }
  if (!open) {
    return <button type="button" onClick={() => setOpen(true)} className="text-cyan-300 hover:underline" data-testid="someone-missing">Someone missing?</button>;
  }
  return (
    <div className="mt-1 rounded-md border border-slate-700 bg-slate-950/60 p-2 space-y-1.5" data-testid="someone-missing-panel">
      <p className="text-slate-300">Only people in Decision reviewers can approve. Pick a teammate to add them. Someone not in the workspace yet has to be invited first.</p>
      <div className="flex flex-wrap items-center gap-2">
        <select value={pick} onChange={(e) => setPick(e.target.value)} className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs text-white max-w-full" aria-label="Teammate to add" data-testid="someone-missing-pick">
          <option value="">{data ? (members.length ? 'Pick a teammate' : 'Everyone here can already approve') : 'Loading the team…'}</option>
          {members.map((m) => <option key={m.id} value={m.id}>{m.full_name || m.name || m.email}{m.full_name || m.name ? ` (${m.email})` : ''}</option>)}
        </select>
        <button type="button" onClick={give} disabled={!pick || busy} title={pick ? '' : 'Pick a teammate first'} className="px-2 py-1 rounded bg-cyan-500 text-white disabled:opacity-40" data-testid="someone-missing-give">Give them Review decisions</button>
        <Link href={inviteHref(decisionKey)} className="text-cyan-300 hover:underline">Invite someone</Link>
        <Link href="/admin/permissions" className="text-slate-400 hover:text-white underline decoration-dotted">Permissions</Link>
        <button type="button" onClick={() => setOpen(false)} className="text-slate-500 hover:text-white">Close</button>
      </div>
      {msg && <p className={msg.ok ? 'text-emerald-300' : 'text-rose-300'} role="status" data-testid="someone-missing-msg">{msg.text}</p>}
    </div>
  );
}

export const SOLE_REASON_MIN = 10;

export function namesText(people: { name: string; email?: string }[], max = 3): string {
  const names = people.map((p) => p.name || p.email || 'someone');
  if (names.length <= max) return names.join(', ');
  return `${names.slice(0, max).join(', ')} and ${names.length - max} more`;
}

// the invite opens with Can approve decisions ticked and a way back to the decision
export function inviteHref(decisionKey?: string | null): string {
  return `/settings/team?invite=1&approver=1${decisionKey ? `&from=${encodeURIComponent(decisionKey)}` : ''}`;
}

export function InviteApprover({ isAdmin, decisionKey }: { isAdmin: boolean; decisionKey?: string | null }) {
  return isAdmin ? (
    <Link href={inviteHref(decisionKey)} className="inline-flex items-center gap-1 text-cyan-300 hover:underline" data-testid="invite-approver">
      <UserPlus className="w-3.5 h-3.5" /> Invite an approver
    </Link>
  ) : (
    <span className="text-slate-400">Ask an admin to invite someone who can approve.</span>
  );
}

export function SelfApprovedBadge({ reason, name }: { reason?: string | null; name?: string }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-200" data-testid="self-approved" title={reason ? `Reason: ${reason}` : undefined}>
      <ShieldAlert className="w-3 h-3" /> Self-approved{name ? ` by ${name}` : ''} as the only approver{reason ? `: “${reason}”` : ''}
    </span>
  );
}

// who signed the review after a raise, by name where the server or the approver list knows it
export function attesters(info: SignOffInfo): string {
  const a = info.attestation;
  if (!a) return '';
  if (a.approved_by_names?.length) return a.approved_by_names.join(', ');
  return (a.approved_by || []).map((id) => info.eligible_approvers.find((e) => String(e.id) === String(id))?.name).filter(Boolean).join(', ');
}

// the plain sentence about who signs: what the tier needs, who can, and that the author can't
export function SignOffSummary({ info, isAdmin, compact, decisionKey, onChanged, authorId }: { info: SignOffInfo; isAdmin: boolean; compact?: boolean; decisionKey?: string; onChanged?: () => void; authorId?: string | null }) {
  const approvals = info.signoffs.filter((s) => (s.decision ?? 'approve') === 'approve');
  const denials = info.signoffs.filter((s) => s.decision === 'deny' || s.decision === 'return');
  const sole = approvals.find((s) => s.sole_operator);
  if (!info.required) {
    return <p className="text-xs text-slate-400" data-testid="signoff-summary">{info.policy_text || 'This tier needs no sign-off. Proposing it approves it.'}</p>;
  }
  // in a one-person workspace the tier rule and the way through are one sentence
  const soleNow = !info.eligible_approvers.length && info.sole_operator_available && !compact;
  return (
    <div className="text-xs text-slate-300 space-y-1" data-testid="signoff-summary">
      <p>
        <span className="text-slate-200">{soleNow ? `${tierName(info.tier)} risk needs one approver who did not write it. Nobody else here can approve, so you sign it yourself with a written reason, which goes on the audit log.` : info.policy_text}</span>{' '}
        {!compact && !info.author_can_approve && (info.eligible_approvers.length || !info.sole_operator_available) && <span className="text-slate-400">The person who proposes it can&apos;t approve it.</span>}{' '}
      </p>
      <details className="text-slate-400" data-testid="signoff-who">
        <summary className="cursor-pointer text-slate-500 hover:text-cyan-300 w-fit">Who can approve?</summary>
        <p className="mt-1 max-w-3xl">
          Anyone in Decision reviewers, which means they can review decisions and sign approvals, other than the person who proposed it. Admins add people under Admin, Permissions, or here with Someone missing.{' '}
          <a href="/docs?doc=08-howto%2F09-decisions#from-draft-to-published" target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline">The how-to, in a new tab</a>
        </p>
      </details>
      {!compact && (
        info.eligible_approvers.length ? (
          <p className="text-slate-400" data-testid="signoff-approvers">
            {info.eligible_approvers.length === 1 ? 'Who can approve: ' : `${info.eligible_approvers.length} people can approve: `}
            <span className="text-slate-200">{namesText(info.eligible_approvers)}</span>.{' '}
            {info.missing_hint?.can_grant && decisionKey && <SomeoneMissing decisionKey={decisionKey} eligible={info.eligible_approvers} onChanged={() => onChanged?.()} authorId={authorId} />}
          </p>
        ) : (
          <p className="text-amber-200" data-testid="signoff-nobody">
            {!soleNow && <>Nobody else in this workspace can approve it.{' '}</>}
            {info.sole_operator_available ? 'Invite someone who can approve to share the sign-off.' : <InviteApprover isAdmin={isAdmin} decisionKey={decisionKey} />}{' '}
            {info.missing_hint?.can_grant && decisionKey && <SomeoneMissing decisionKey={decisionKey} eligible={info.eligible_approvers} onChanged={() => onChanged?.()} authorId={authorId} />}
          </p>
        )
      )}
      {denials.length > 0 && (
        <p className="text-rose-200" data-testid="signoff-denied">
          {denials.map((d) => `${d.decision === 'return' ? 'Sent back' : 'Denied'} by ${d.name}${d.reason ? `: “${d.reason}”` : ''}`).join(' ')}
        </p>
      )}
      {info.attested_under && <p className="text-emerald-200" data-testid="signoff-attested">Reviewed again at {info.attested_under} risk after the tier was raised{attesters(info) ? `, by ${attesters(info)}` : ''}.</p>}
      {approvals.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="signoff-done">
          {sole ? <SelfApprovedBadge reason={sole.reason} name={sole.name} /> : (
            approvals.map((s) => (
              <span key={`${s.user_id}-${s.at}`} className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-emerald-200">
                <BadgeCheck className="w-3 h-3" /> Approved by {s.name}
              </span>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// the one-person workspace way through: a written reason, a clear warning and a confirmation
export function SoleOperatorDialog({ approvalId, title, onClose, onDone, initialReason = '' }: { approvalId: string; title: string; onClose: () => void; onDone: () => void; initialReason?: string }) {
  const [reason, setReason] = useState(initialReason);
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const left = SOLE_REASON_MIN - reason.trim().length;
  const ok = left <= 0 && sure;

  async function go() {
    if (!ok) return;
    setBusy(true);
    setErr(null);
    const r = await apiFetch(`/api/approvals/${encodeURIComponent(approvalId)}/signoff`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'approve', reason: reason.trim(), sole_operator: true }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error) setErr(decisionErrorText(r.errorDetail?.error_code, r.error));
    else onDone();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="sole-title" data-testid="sole-dialog">
      <div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h2 id="sole-title" className="text-base font-semibold text-white">Approve as the only approver</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-5 py-4 space-y-3">
          <p className="text-sm text-slate-300">{title}</p>
          <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>Nobody else in this workspace can approve this, so you can sign it off yourself. It is recorded as self-approved with your reason and shows that way wherever the sign-off appears. Any other admins are told. <Link href="/docs?doc=08-howto%2F09-decisions#working-alone" className="underline">How this works</Link></span>
          </div>
          <div>
            <label htmlFor="sole-reason" className="block text-xs text-slate-400 mb-1">Why it is safe to approve your own change</label>
            <textarea
              id="sole-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className={`w-full bg-slate-950 border rounded-md px-2 py-1.5 text-sm text-white placeholder:text-slate-600 placeholder:italic ${reason && left > 0 ? 'border-amber-500/60' : 'border-slate-700'}`}
              placeholder="what you checked, and why it can't wait for a second person"
              aria-invalid={!!reason && left > 0}
              data-testid="sole-reason"
            />
            <p className={`text-[11px] ${left > 0 ? 'text-slate-500' : 'text-emerald-300'}`}>{left > 0 ? `At least ${SOLE_REASON_MIN} characters, ${left} more to go.` : 'Thanks, that goes on the record.'}</p>
          </div>
          <label className="flex items-start gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-0.5 accent-amber-500" data-testid="sole-confirm-check" />
            I understand this is recorded as self-approved, with my reason.
          </label>
          {err && <p className="text-xs text-rose-300" role="alert" data-testid="sole-error">{err}</p>}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 px-5 py-3 border-t border-slate-800">
          {!ok && <span className="mr-auto text-[11px] text-slate-500">{left > 0 ? 'Write the reason first.' : 'Tick the box to confirm.'}</span>}
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={go} disabled={!ok || busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-40" data-testid="sole-approve">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Approve it myself
          </button>
        </div>
      </div>
    </div>
  );
}

// for a waiting tier change or review: the only approver can sign it from the decision page too
export function SoleApproveButton({ approvalId, title, onDone, testId }: { approvalId: string; title: string; onDone: () => void; testId?: string }) {
  const { data, mutate } = useApi<{ status: string; sole_operator_available?: boolean }>(`/api/approvals/${encodeURIComponent(approvalId)}`, { dedupingInterval: 0 });
  const [open, setOpen] = useState(false);
  if (!data?.sole_operator_available || data.status !== 'pending') return null;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="text-xs px-2 py-1 rounded-md border border-amber-500/50 text-amber-200 hover:bg-amber-500/10" data-testid={testId}>
        Approve as the only approver
      </button>
      {open && <SoleOperatorDialog approvalId={approvalId} title={title} onClose={() => setOpen(false)} onDone={() => { setOpen(false); mutate(); onDone(); }} />}
    </>
  );
}

// deny or send back always carries a reason, so the person who asked learns why
export function ReasonDialog({ title, intro, verb, min = 5, placeholder, onClose, onConfirm, testId = 'reason-dialog' }: {
  title: string; intro: string; verb: string; min?: number; placeholder: string; onClose: () => void; onConfirm: (reason: string) => Promise<string | null>; testId?: string;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const left = min - reason.trim().length;
  async function go() {
    if (left > 0) return;
    setBusy(true);
    const e = await onConfirm(reason.trim());
    setBusy(false);
    if (e) setErr(e);
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby={`${testId}-title`} data-testid={testId}>
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
          <h2 id={`${testId}-title`} className="text-base font-semibold text-white">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-5 py-4 space-y-2">
          <p className="text-sm text-slate-300">{intro}</p>
          <textarea value={reason} onChange={(e) => { setReason(e.target.value); setErr(null); }} rows={3} autoFocus placeholder={placeholder} className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white placeholder:text-slate-600 placeholder:italic" aria-label="Reason" data-testid={`${testId}-reason`} />
          <p className={`text-[11px] ${left > 0 ? 'text-slate-500' : 'text-emerald-300'}`}>{left > 0 ? `Write at least ${min} characters, ${left} more to go. The person who asked sees it.` : 'They will see this.'}</p>
          {err && <p className="text-xs text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={go} disabled={left > 0 || busy} title={left > 0 ? 'Write the reason first' : ''} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-rose-600 text-white hover:bg-rose-500 disabled:opacity-40" data-testid={`${testId}-confirm`}>
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} {verb}
          </button>
        </div>
      </div>
    </div>
  );
}
