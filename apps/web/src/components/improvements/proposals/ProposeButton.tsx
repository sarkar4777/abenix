'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Loader2, Sparkles } from 'lucide-react';
import type { ClusterRow } from '@/lib/improvements';
import { isWorking, proposalsApi } from '@/lib/improvement-proposals';
import { ProofSteps, StateChip } from './parts';
import { useProposal } from './useProposal';

function Live({ proposal, agentId }: { proposal: unknown; agentId: string }) {
  const { p } = useProposal(proposal);
  const href = `/agents/${encodeURIComponent(agentId)}/improvements?proposal=${encodeURIComponent(p.id)}`;
  return (
    <div className="w-full space-y-2" data-testid="propose-live" data-proposal-id={p.id} data-state={p.state}>
      <div className="flex flex-wrap items-center gap-2">
        <StateChip p={p} />
        <Link href={href} className="text-xs text-cyan-300 hover:underline" data-testid="propose-see-proof">
          See the proof
        </Link>
      </div>
      {isWorking(p) && <ProofSteps steps={p.progress?.steps || []} message={p.progress?.waiting || p.progress?.message} />}
    </div>
  );
}

export default function ProposeButton({ cluster }: { cluster: ClusterRow }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [made, setMade] = useState<unknown>(null);
  const agentId = cluster.agent?.id || '';
  const existing = made || cluster.proposal;
  const closed = cluster.state === 'dismissed' || cluster.state === 'fixed';

  if (existing && !closed) {
    const st = (existing as { state?: string }).state || '';
    if (['drafting', 'proving', 'awaiting_approval', 'approved', 'released'].includes(st)) {
      return <Live proposal={existing} agentId={agentId} />;
    }
  }

  async function go() {
    setBusy(true);
    setErr(null);
    const r = await proposalsApi.propose(cluster.id);
    setBusy(false);
    if (r.error || !r.data) {
      if (r.status === 403) setErr(`${r.error} Ask an admin for Propose improvements.`);
      else if (r.status === 404 && !r.code) setErr('Proposing fixes is not switched on here yet.');
      else setErr(r.error || 'The fix could not be proposed.');
      return;
    }
    setMade(r.data);
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={go}
        disabled={busy || closed}
        title={closed ? 'This group is closed.' : undefined}
        className="inline-flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
        data-testid="propose-fix"
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Propose a fix
      </button>
      {closed && <span className="text-[11px] text-slate-500">This group is closed, so there is nothing to fix.</span>}
      {err && (
        <span role="alert" className="text-[11px] text-rose-300" data-testid="propose-error">
          {err}
        </span>
      )}
    </div>
  );
}
