export interface CacheMeta {
  cachedAt: string | null;
  ageSeconds: number | null;
  ttlSeconds: number | null;
  fresh: boolean;
}

export function readCacheEnvelope(j: any): { payload: any; meta: CacheMeta } | null {
  const d = j?.data;
  if (!d || !d.payload) return null;
  return {
    payload: d.payload,
    meta: {
      cachedAt: d.cached_at || null,
      ageSeconds: typeof d.age_seconds === 'number' ? d.age_seconds : null,
      ttlSeconds: typeof d.ttl_seconds === 'number' ? d.ttl_seconds : null,
      fresh: !!d.fresh,
    },
  };
}

export function formatAge(seconds: number | null): string {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}
