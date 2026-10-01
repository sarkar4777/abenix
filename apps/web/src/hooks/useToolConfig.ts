'use client';

import { useMemo } from 'react';
import { useApi } from '@/hooks/useApi';
import type { ToolConfigInfo } from '@/components/CredentialBadge';

interface ToolRow {
  id: string;
  config?: ToolConfigInfo;
}

/** tool id -> credential state, from /api/tools, resolved for the caller's tenant. Shared through SWR so one fetch serves every component. */
export function useToolConfigMap(): Record<string, ToolConfigInfo> {
  const { data } = useApi<ToolRow[] | { tools: ToolRow[] }>('/api/tools', { dedupingInterval: 30_000 });
  return useMemo(() => {
    const rows: ToolRow[] = Array.isArray(data) ? data : (data as { tools?: ToolRow[] } | null)?.tools || [];
    const out: Record<string, ToolConfigInfo> = {};
    for (const r of rows) if (r.config) out[r.id] = r.config;
    return out;
  }, [data]);
}

export function useIsAdmin(): boolean {
  const { data } = useApi<{ is_admin?: boolean }>('/api/me/permissions', { dedupingInterval: 60_000 });
  return Boolean(data?.is_admin);
}
