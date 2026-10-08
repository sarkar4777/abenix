'use client';

import { useApi } from '@/hooks/useApi';

export interface BillingMode {
  flatRate: boolean;
  loaded: boolean;
}

export const SUBSCRIPTION_LABEL = 'Claude subscription';
export const SUBSCRIPTION_NOTE = 'Claude runs use a flat-rate subscription, so they show $0 per run.';

// one cached call shared by every cost on the page
export function useBillingMode(): BillingMode {
  const { data, isLoading } = useApi<{ flat_rate_billing: boolean }>('/api/analytics/billing-mode', {
    dedupingInterval: 60_000,
  });
  return { flatRate: !!data?.flat_rate_billing, loaded: !isLoading };
}
