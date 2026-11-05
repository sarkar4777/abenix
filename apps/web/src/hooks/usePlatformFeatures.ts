'use client';

import { useApi } from '@/hooks/useApi';

export const PLATFORM_FEATURES_PATH = '/api/platform/features';

export interface PlatformFeatures {
  marketplace: boolean;
  monetization: boolean;
  source?: { marketplace?: 'admin' | 'default'; monetization?: 'admin' | 'default' };
  defaults?: { marketplace?: boolean; monetization?: boolean };
}

const OFFLINE = 'Could not reach the server. Check your connection and try again.';

// a browser "Failed to fetch" means nothing to a person
export function plainError(message: string | null | undefined, code?: string, fallback = 'Something went wrong. Try again.') {
  if (code === 'NETWORK_ERROR' || /failed to fetch|networkerror|load failed/i.test(message || '')) return OFFLINE;
  return message || fallback;
}

// can_change is the API's is_platform_operator answer, and a failed read leaves the server to refuse
export function usePlatformOperator() {
  const { data, isLoading } = useApi<{ can_change?: boolean; operator_rule?: string }>('/api/admin/platform-features', {
    dedupingInterval: 15_000,
  });
  return {
    settled: !isLoading,
    readOnly: !!data && data.can_change !== true,
    rule: data?.operator_rule,
  };
}

// Read at runtime so an admin change applies without a rebuild. Both read as off until loaded.
export function usePlatformFeatures() {
  const { data, error, isLoading, mutate } = useApi<PlatformFeatures>(PLATFORM_FEATURES_PATH, {
    dedupingInterval: 15_000,
  });
  return {
    features: data,
    loaded: !!data,
    marketplace: data?.marketplace === true,
    monetization: data?.monetization === true,
    error,
    isLoading,
    mutate,
  };
}
