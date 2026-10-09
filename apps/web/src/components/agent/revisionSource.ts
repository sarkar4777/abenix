export const SOURCE_BADGES: Record<string, { label: string; className: string }> = {
  edit: { label: 'Edit', className: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/20' },
  healing: { label: 'Healing', className: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20' },
  improvement: { label: 'Improvement', className: 'text-purple-300 bg-purple-500/10 border-purple-500/20' },
  revert: { label: 'Revert', className: 'text-amber-300 bg-amber-500/10 border-amber-500/20' },
  import: { label: 'Import', className: 'text-slate-300 bg-slate-500/10 border-slate-500/20' },
};

export function sourceBadge(source?: string | null) {
  return SOURCE_BADGES[source || 'edit'] || SOURCE_BADGES.edit;
}

export function proofLink(agentId: string, proposalId?: string | null): string | null {
  return proposalId ? `/agents/${agentId}/improvements?proposal=${encodeURIComponent(proposalId)}` : null;
}
