import { useApi } from '@/hooks/useApi';

export interface MyPermissions {
  role: string;
  user_id?: string;
  is_admin: boolean;
  features: Record<string, boolean>;
  capabilities?: string[];
  can_approve_decisions?: boolean;
}

// Mirrors app/core/capabilities.py holds(): "*", exact, "group.*", and a grant
// without a qualifier covering the qualified form (approvals.sign covers approvals.sign:legal).
export function holds(granted: readonly string[] | undefined, cap: string): boolean {
  if (!granted) return false;
  if (granted.includes('*') || granted.includes(cap)) return true;
  const base = cap.split(':', 1)[0];
  if (granted.includes(base)) return true;
  const group = base.slice(0, base.lastIndexOf('.'));
  return granted.includes(`${group}.*`);
}

// A failed load is "unknown, retrying", never a quiet downgrade to view only.
// loading stays true until the permissions arrive, failed tells the page to say so.
export function useMyPermissions() {
  const { data, error, isLoading, mutate } = useApi<MyPermissions>('/api/me/permissions', {
    refreshInterval: (latest: unknown) => (latest && (latest as { error?: unknown }).error ? 4000 : 0),
  });
  const failed = !data && !!error;
  return { perms: data, loading: isLoading || failed, failed, retry: mutate };
}

export function useCapability(cap: string): { allowed: boolean; loading: boolean } {
  const { perms, loading } = useMyPermissions();
  return { allowed: holds(perms?.capabilities, cap), loading };
}
