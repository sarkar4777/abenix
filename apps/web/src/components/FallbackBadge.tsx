'use client';

import { ArrowLeft } from 'lucide-react';

interface FallbackBadgeProps {
  actual_model: string;
  requested_model: string;
  reason?: string;
}

export function FallbackBadge({ actual_model, requested_model, reason }: FallbackBadgeProps) {
  if (!actual_model || !requested_model) return null;
  if (actual_model === requested_model) return null;

  const reasonText = reason ? `: ${reason.replace(/_/g, ' ')}` : '';

  return (
    <span
      data-testid="fallback-badge"
      title={`Requested ${requested_model}; actually ran on ${actual_model}${reasonText}`}
      className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-200"
    >
      <span>Ran on </span>
      <span className="font-mono">{actual_model}</span>
      <ArrowLeft className="w-3 h-3 opacity-70" />
      <span>fallback from </span>
      <span className="font-mono">{requested_model}</span>
      {reason && <span className="opacity-80">{reasonText}</span>}
    </span>
  );
}

export default FallbackBadge;
