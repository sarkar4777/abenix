import { useApi } from '@/hooks/useApi';

export interface MyPermissions {
  role: string;
  is_admin: boolean;
  features: Record<string, boolean>;
  capabilities?: string[];
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

export function useMyPermissions() {
  const { data, isLoading } = useApi<MyPermissions>('/api/me/permissions');
  return { perms: data, loading: isLoading };
}

export function useCapability(cap: string): { allowed: boolean; loading: boolean } {
  const { perms, loading } = useMyPermissions();
  return { allowed: holds(perms?.capabilities, cap), loading };
}
