'use client';

import { useState } from 'react';
import { Archive, ArchiveRestore, PowerOff } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { tierName, type Tier } from '@/lib/decisions';
import { SOLE_REASON_MIN } from './SignOff';

export type GuardedKind = 'retire' | 'archive' | 'restore';

const ICON = { retire: PowerOff, archive: Archive, restore: ArchiveRestore };
const VERB = { retire: 'Retire', archive: 'Archive', restore: 'Restore' };
export const REASON_MIN = 5;

// retire, archive and restore: what happens after, and at high tiers that a second person signs it first
export default function GuardedActionDialog({
  kind, title, effect, tier, needsSignoff, signAlone = false, neverLive = false, placeholder, busy, onClose, onConfirm,
}: {
  kind: GuardedKind;
  title: string;
  effect: string;
  tier: Tier;
  needsSignoff: boolean;
  // nobody else here can approve, so the person asking signs it in the same step
  signAlone?: boolean;
  // nothing was ever published, so nothing needs signing off
  neverLive?: boolean;
  placeholder?: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<string | null>;
}) {
  const [reason, setReason] = useState('');
  const [sure, setSure] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sole = needsSignoff && signAlone;
  const min = sole ? SOLE_REASON_MIN : REASON_MIN;
  const short = reason.trim().length < min;
  const blocked = (needsSignoff && short) || (sole && !sure);
  const t = tierName(tier);
  const gate = !needsSignoff
    ? neverLive
      ? ' No sign-off is needed, so it happens straight away.'
      : ` ${t} risk needs no sign-off for this, so it happens straight away.`
    : sole
      ? ` ${t} risk needs a second person to approve this, and you are the only person here who can. You sign it yourself in this step, with the reason below. It is recorded as self-approved.`
      : ` ${t} risk needs a second person to approve this first. Your request goes to Approvals with your reason, and nothing changes until it is approved.`;
  return (
    <ConfirmModal
      open
      onClose={onClose}
      onConfirm={async () => { if (blocked) return; const e = await onConfirm(reason.trim()); if (e) setErr(e); }}
      loading={busy}
      variant={kind === 'restore' ? 'warning' : 'danger'}
      icon={ICON[kind]}
      title={title}
      description={`${effect}${gate} This is recorded in the audit log.`}
      confirmLabel={!needsSignoff ? VERB[kind] : sole ? `Sign it myself and ${VERB[kind].toLowerCase()}` : 'Ask for sign-off'}
      confirmDisabled={blocked}
      confirmTestId={`${kind}-confirm`}
    >
      <div>
        <label htmlFor={`${kind}-reason`} className="block text-xs text-slate-400 mb-1">Why{needsSignoff ? ' (required)' : ' (optional)'}</label>
        <textarea
          id={`${kind}-reason`}
          value={reason}
          onChange={(e) => { setReason(e.target.value); setErr(null); }}
          rows={2}
          className="w-full bg-slate-950 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-white placeholder:text-slate-600 placeholder:italic"
          placeholder={placeholder || (kind === 'restore' ? 'why it should come back' : kind === 'retire' ? 'why this version should stop answering' : 'why it should leave the list')}
          data-testid={`${kind}-reason`}
        />
        {needsSignoff && short && <p className="text-[11px] text-slate-500">Write a reason of at least {min} characters. {sole ? 'It goes on the audit log.' : 'The approver reads it.'}</p>}
        {sole && (
          <label className="mt-2 flex items-start gap-2 text-xs text-amber-100">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-0.5 accent-amber-500" data-testid={`${kind}-sole-sure`} />
            I understand this is recorded as self-approved, with my reason, and any other admins are told.
          </label>
        )}
        {err && <p className="text-xs text-rose-300" role="alert">{err}</p>}
      </div>
    </ConfirmModal>
  );
}
