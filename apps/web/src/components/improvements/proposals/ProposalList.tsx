'use client';

import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Wrench } from 'lucide-react';
import type { ProposalRow } from '@/lib/improvements';
import { fixedText, isWorking } from '@/lib/improvement-proposals';
import { StateChip } from './parts';
import ProofBody from './ProofBody';
import ReleaseWatch from './ReleaseWatch';
import { focusedProposalId, useProposal } from './useProposal';

function ProposalItem({ proposal, focusId }: { proposal: ProposalRow; focusId?: string | null }) {
  const { p, setP, error } = useProposal(proposal);
  const [open, setOpen] = useState(() => isWorking(p));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if ((focusId ?? focusedProposalId()) === p.id) {
      setOpen(true);
      ref.current?.scrollIntoView({ block: 'start' });
    }
  }, [p.id, focusId]);

  if (p.state === 'released' || p.state === 'kept' || p.state === 'rolled_back') {
    return <ReleaseWatch proposal={proposal} />;
  }
  const step = (p.progress?.steps || []).find((s) => s.state === 'running');
  return (
    <div ref={ref} className="rounded-xl border border-slate-700/60 bg-slate-800/30 p-4" data-testid="proposal-item" data-proposal-id={p.id} data-state={p.state}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-2 text-left"
        data-testid="proposal-toggle"
      >
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        <StateChip p={p} />
        <span className="min-w-0 flex-1 break-words text-sm text-white">{p.cluster?.title || 'A group of lessons'}</span>
        <span className="text-[11px] text-slate-400" data-testid="proposal-summary">
          {isWorking(p) ? (p.progress?.waiting ? 'Waiting in line' : step ? step.label : 'Queued') : p.proof ? fixedText(p.proof) : p.change_label}
        </span>
      </button>
      {error && <p className="mt-2 text-xs text-rose-300" role="alert">{error}</p>}
      {open && (
        <div className="mt-3 border-t border-slate-800 pt-3">
          <ProofBody p={p} onChange={setP} />
        </div>
      )}
    </div>
  );
}

export default function ProposalList({ agentId, proposals, focusId }: { agentId: string; proposals: ProposalRow[]; focusId?: string | null }) {
  if (!proposals.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-700/60 bg-slate-800/20 p-5 text-center" data-testid="proposal-list-empty" data-agent-id={agentId}>
        <Wrench className="mx-auto mb-2 h-6 w-6 text-slate-600" />
        <p className="text-sm text-slate-300">No fixes proposed yet.</p>
        <p className="mt-1 text-xs text-slate-500">
          Pick a group of lessons above and choose Propose a fix. Groups that grow past the threshold get one on their own.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-3" data-testid="proposal-list" data-agent-id={agentId}>
      {proposals.map((p) => (
        <ProposalItem key={p.id} proposal={p} focusId={focusId} />
      ))}
    </div>
  );
}
