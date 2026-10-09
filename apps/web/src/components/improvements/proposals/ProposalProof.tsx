'use client';

import type { ProposalRow } from '@/lib/improvements';
import { StateChip } from './parts';
import ProofBody from './ProofBody';
import ReleaseWatch from './ReleaseWatch';
import { useProposal } from './useProposal';

export default function ProposalProof({ proposal }: { proposal: ProposalRow }) {
  const { p, setP, error } = useProposal(proposal);
  const released = p.state === 'released' || p.state === 'kept' || p.state === 'rolled_back';
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <StateChip p={p} />
        {p.cluster?.title && <span className="break-words text-xs text-slate-300">{p.cluster.title}</span>}
      </div>
      {error && <p className="text-xs text-rose-300" role="alert">{error}</p>}
      {released ? <ReleaseWatch proposal={proposal} /> : <ProofBody p={p} onChange={setP} />}
    </div>
  );
}
