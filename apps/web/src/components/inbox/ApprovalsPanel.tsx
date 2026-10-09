'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, Loader2, ShieldCheck, XCircle } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { isActionGate, levelLabel, relTime, signoffApproval } from '@/lib/autonomy';
import { RELEASE_GATE, canSign, refreshInboxCounts, type SignableRow } from '@/lib/inbox';
import ApprovalActionRow from '@/components/autonomy/ApprovalActionRow';

interface Row extends SignableRow {
  title: string;
  status: string;
  payload: Record<string, unknown>;
  created_at?: string | null;
  expires_at?: string | null;
}

const KIND: Record<string, string> = {
  human_approval: 'Agent gate',
  decision_publish: 'Rule change',
  'autonomy.promote': 'Promotion',
};

function summary(row: Row): string | null {
  const p = row.payload || {};
  if (row.gate_kind === 'autonomy.promote') {
    const agent = (p.agent as { name?: string } | undefined)?.name;
    const from = typeof p.from === 'number' ? p.from : null;
    const to = typeof p.to === 'number' ? p.to : null;
    const move = from !== null && to !== null ? `${levelLabel(from)} to ${levelLabel(to)}` : 'move up a level';
    return agent ? `${agent}: ${move}` : move;
  }
  if (typeof p.summary === 'string') return p.summary;
  if (typeof p.details === 'string' && p.details) return p.details;
  return null;
}

function evidenceLink(row: Row): { href: string; label: string } | null {
  const p = row.payload || {};
  if (row.gate_kind === 'decision_publish' && typeof p.link === 'string') return { href: p.link, label: 'Review the rules' };
  if (row.gate_kind === 'autonomy.promote' && typeof p.grant_id === 'string') {
    return { href: `/autonomy/${encodeURIComponent(p.grant_id)}`, label: 'See the evidence' };
  }
  return null;
}

// a compact version of the Approvals page card, approve and deny right here
function QuickRow({ row, busy, onDecide }: { row: Row; busy: boolean; onDecide: (id: string, d: 'approve' | 'deny') => Promise<string | null> }) {
  const [err, setErr] = useState<string | null>(null);
  const text = summary(row);
  const link = evidenceLink(row);
  const decide = async (d: 'approve' | 'deny') => {
    setErr(null);
    const e = await onDecide(row.id, d);
    if (e) setErr(e);
  };
  return (
    <div className="mb-3 rounded-xl border border-slate-700/50 bg-slate-800/40 p-4" data-testid="inbox-approval" data-approval-id={row.id}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <ShieldCheck className="h-4 w-4 shrink-0 text-cyan-400" />
            <h3 className="min-w-0 break-words text-sm font-semibold text-white">{row.title || 'Approval requested'}</h3>
            {row.gate_kind && KIND[row.gate_kind] && (
              <span className="rounded-full border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] text-cyan-300">{KIND[row.gate_kind]}</span>
            )}
          </div>
          {text && <p className="mt-1 break-words text-xs text-slate-400">{text}</p>}
          <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-500">
            {row.created_at && <span>Asked {relTime(row.created_at)}</span>}
            {link && <Link href={link.href} className="text-cyan-300 hover:underline">{link.label}</Link>}
          </div>
        </div>
        <div className="flex w-full shrink-0 gap-2 sm:w-auto">
          <button
            type="button"
            disabled={busy}
            onClick={() => decide('approve')}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-xs font-medium text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50 sm:flex-none"
            data-testid="inbox-approve"
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> Approve
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => decide('deny')}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-500/40 bg-rose-500/15 px-3 py-2 text-xs font-medium text-rose-300 hover:bg-rose-500/25 disabled:opacity-50 sm:flex-none"
            data-testid="inbox-deny"
          >
            <XCircle className="h-3.5 w-3.5" /> Deny
          </button>
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
    const mine = (r.data || []).filter((a) => a.status === 'pending' && a.gate_kind !== RELEASE_GATE && canSign(a, me, caps));
    setRows(mine);
    onCount?.(mine.length);
  }, [me, caps, onCount]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (id: string, decision: 'approve' | 'deny', reason?: string, edited?: Record<string, unknown>) => {
    setBusyId(id);
    const r = await signoffApproval(id, decision, reason, edited);
    setBusyId(null);
    await load();
    refreshInboxCounts();
    return r.error;
  };

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
      <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center" data-testid="inbox-approvals-empty">
        <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-400/40" />
        <p className="text-sm text-slate-400">No approvals waiting on you. Requests you are allowed to sign show here.</p>
      </div>
    );
  }
  return (
    <div data-testid="inbox-approvals">
      {rows.map((row) =>
        isActionGate(row.gate_kind) ? (
          <ApprovalActionRow
            key={row.id}
            row={{ ...row, status: row.status, title: row.title }}
            onDecide={decide}
            busy={busyId === row.id}
          />
        ) : (
          <QuickRow key={row.id} row={row} busy={busyId === row.id} onDecide={(id, d) => decide(id, d)} />
        ),
      )}
    </div>
  );
}
