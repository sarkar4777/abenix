'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { RELEASE_GATE, canSign, refreshInboxCounts, type SignableRow } from '@/lib/inbox';
import ImprovementApprovalCard, { type Decided } from '@/components/improvements/proposals/ImprovementApprovalCard';
import ReleasedNext from '@/components/improvements/proposals/ReleasedNext';

interface Row extends SignableRow {
  status: string;
}

export default function ProposalsPanel({
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
  const [decided, setDecided] = useState<Decided | null>(null);

  const load = useCallback(async () => {
    const r = await apiFetch<Row[]>('/api/approvals?mine=1&status=pending', { silent: true });
    setLoading(false);
    if (r.error && !r.data) {
      setError('Proposed fixes could not be loaded. Check your connection and try again.');
      return;
    }
    setError(null);
    const mine = (r.data || []).filter((a) => a.status === 'pending' && a.gate_kind === RELEASE_GATE && canSign(a, me, caps));
    setRows(mine);
    onCount?.(mine.length);
  }, [me, caps, onCount]);

  useEffect(() => {
    load();
  }, [load]);

  const onDecided = useCallback(async (d: Decided) => {
    setDecided(d);
    await load();
    refreshInboxCounts();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading proposed fixes
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
  const next = <ReleasedNext decided={decided} onDismiss={() => setDecided(null)} />;
  if (rows.length === 0) {
    return (
      <>
      {next}
      <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center" data-testid="inbox-proposals-empty">
        <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-400/40" />
        <p className="text-sm text-slate-400">No proposed fixes waiting on you. A fix only arrives here after it passed its proof.</p>
        <Link href="/improvements" className="mt-2 inline-block text-xs text-cyan-300 hover:underline">Open Improvements</Link>
      </div>
      </>
    );
  }
  return (
    <div className="space-y-3" data-testid="inbox-proposals">
      {next}
      {rows.map((row) => (
        <ImprovementApprovalCard key={row.id} approval={row as unknown as Record<string, unknown>} onDecided={onDecided} />
      ))}
    </div>
  );
}
