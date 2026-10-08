'use client';

import { useState } from 'react';
import ActionCard from './ActionCard';
import type { ActionCardData } from '@/lib/autonomy';

export interface ActionApprovalRow {
  id: string;
  title: string;
  status: string;
  payload: Record<string, unknown>;
  gate_kind?: string | null;
  created_at?: string | null;
  expires_at?: string | null;
}

export type DecideFn = (
  id: string,
  decision: 'approve' | 'deny',
  reason?: string,
  editedArguments?: Record<string, unknown>,
) => Promise<string | null>;

// An approval raised by an agent at Asks first, shown as an action card.
export default function ApprovalActionRow({ row, onDecide, busy }: { row: ActionApprovalRow; onDecide: DecideFn; busy: boolean }) {
  const [err, setErr] = useState<string | null>(null);
  const card = (row.payload || {}) as ActionCardData;
  const pending = row.status === 'pending';
  const status = pending ? 'pending' : row.status === 'approved' ? 'approved' : row.status === 'denied' ? 'rejected' : row.status;

  async function approve(edited?: Record<string, unknown>) {
    setErr(null);
    const e = await onDecide(row.id, 'approve', edited ? 'Approved with edits' : undefined, edited);
    if (e) setErr(e);
  }

  async function reject(note: string) {
    setErr(null);
    const e = await onDecide(row.id, 'deny', note);
    if (e) setErr(e);
  }

  return (
    <div className="mb-3" data-testid="approval-action-row" data-approval-id={row.id}>
      <ActionCard
        card={card}
        action={{ id: card.action_id || row.id, status, created_at: row.created_at, agent: card.agent, level_at_time: card.level ?? null }}
        context={pending ? 'approval' : 'readonly'}
        busy={busy}
        error={err}
        onApprove={approve}
        onReject={reject}
      />
    </div>
  );
}
