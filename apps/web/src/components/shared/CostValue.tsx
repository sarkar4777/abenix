'use client';

import { SUBSCRIPTION_LABEL, SUBSCRIPTION_NOTE, useBillingMode } from '@/hooks/useBillingMode';

export function formatCostValue(cost: number | null | undefined, digits = 4): string {
  if (cost == null || Number.isNaN(cost)) return '—';
  if (cost === 0) return '$0';
  return cost >= 1 ? `$${cost.toFixed(2)}` : `$${cost.toFixed(digits)}`;
}

// A per-run or total cost. On a Claude subscription a zero reads "Claude subscription",
// a non-zero amount (another provider) keeps its dollars and gains a small tag.
export function CostValue({
  cost,
  digits = 4,
  flatRate,
  className = '',
  testId,
}: {
  cost: number | null | undefined;
  digits?: number;
  flatRate?: boolean;
  className?: string;
  testId?: string;
}) {
  const mode = useBillingMode();
  const sub = flatRate ?? mode.flatRate;
  if (!sub) {
    return <span className={className} data-testid={testId}>{formatCostValue(cost, digits)}</span>;
  }
  const zero = !cost;
  return (
    <span className={className} data-testid={testId} data-billing="subscription" title={SUBSCRIPTION_NOTE}>
      {zero ? '$0' : formatCostValue(cost, digits)}
      <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 ring-1 ring-violet-500/30 whitespace-nowrap">
        {zero ? SUBSCRIPTION_LABEL : `+ ${SUBSCRIPTION_LABEL}`}
      </span>
    </span>
  );
}

// one line under a total or a chart
export function SubscriptionNote({ flatRate, className = '' }: { flatRate?: boolean; className?: string }) {
  const mode = useBillingMode();
  if (!(flatRate ?? mode.flatRate)) return null;
  return (
    <p className={`text-[11px] text-violet-300/80 ${className}`} data-testid="subscription-cost-note">
      {SUBSCRIPTION_NOTE}
    </p>
  );
}
