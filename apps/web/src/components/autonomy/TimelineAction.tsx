'use client';

import { useState } from 'react';
import ActionCard, { type ReviewAnswer } from './ActionCard';
import { autonomyApi, signoffApproval, signoffErrorText, type ActionCardData, type ActionRow } from '@/lib/autonomy';

interface Props {
  action: ActionRow;
  canFollowUp?: boolean;
  onChanged: (row: ActionRow) => void;
  onRefresh: () => void;
}

function cardOf(a: ActionRow): ActionCardData {
  return a.card || {
    action_id: a.id,
    action_type: a.action_type ? { key: a.action_type.key, label: a.action_type.label } : null,
    agent: a.agent,
    level: a.level_at_time,
    target: a.target,
    arguments: a.arguments,
    intent: a.intent,
    prediction: a.prediction,
  };
}

// One timeline row. Waiting approvals and unanswered watched actions can be handled in place.
export default function TimelineAction({ action, canFollowUp = false, onChanged, onRefresh }: Props) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const approvalId = action.status === 'pending' ? action.approval_id : null;
  const reviewable = action.status === 'watching' && !action.reviewer_answer;
  const context = approvalId ? 'approval' : reviewable ? 'review' : 'timeline';

  async function decide(decision: 'approve' | 'deny', reason?: string, edited?: Record<string, unknown>) {
    if (!approvalId) return;
    setBusy(true);
    setErr(null);
    const r = await signoffApproval(approvalId, decision, reason, edited);
    setBusy(false);
    const e = signoffErrorText(r);
    if (e) { setErr(e); return; }
    onRefresh();
  }

  async function review(answer: ReviewAnswer, alternative?: string) {
    setBusy(true);
    setErr(null);
    const r = await autonomyApi.review(action.id, answer, alternative);
    setBusy(false);
    if (r.error) {
      setErr(r.status === 403 ? 'You need the actions.review permission for this.' : r.error);
      return;
    }
    if (r.data) onChanged(r.data);
    onRefresh();
  }

  return (
    <ActionCard
      card={cardOf(action)}
      action={action}
      context={context}
      busy={busy}
      error={err}
      canFollowUp={canFollowUp}
      onChanged={onChanged}
      onApprove={(edited) => decide('approve', edited ? 'Approved with edits' : undefined, edited)}
      onReject={(note) => decide('deny', note)}
      onReview={review}
    />
  );
}
