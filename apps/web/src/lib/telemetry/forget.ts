// Forgetting devices: they leave the list and free their place in the limit, their history stays.
import { apiFetch } from '@/lib/api-client';
import { explainTelemetryError } from './errors';

export interface ForgetSample { group: string; node: string; device: string; offline_at?: string | number | null; last_seen?: string | number | null; connection_id?: string | null }

export interface BulkResult { dry_run: boolean; matched: number; forgotten: number; remaining: number; sample: ForgetSample[]; history_kept?: boolean }

export interface BulkQuery { offline_for_s: number; group?: string; node_glob?: string; connection_id?: string; limit?: number }

export const OFFLINE_FOR: Array<{ s: number; label: string }> = [
  { s: 60, label: 'more than 1 minute' },
  { s: 600, label: 'more than 10 minutes' },
  { s: 3600, label: 'more than 1 hour' },
  { s: 21600, label: 'more than 6 hours' },
  { s: 86400, label: 'more than 1 day' },
  { s: 604800, label: 'more than 7 days' },
  { s: 2592000, label: 'more than 30 days' },
];

export const offlineLabel = (s: number) => OFFLINE_FOR.find((o) => o.s === s)?.label ?? `more than ${Math.round(s / 60)} minutes`;

export type ForgetOutcome =
  | { kind: 'done'; count: number }
  | { kind: 'online'; message: string }
  | { kind: 'error'; message: string };

export async function forgetOne(group: string, node: string, device: string | null, force = false): Promise<ForgetOutcome> {
  const qs = new URLSearchParams();
  if (device) qs.set('device', device);
  qs.set('force', force ? 'true' : 'false');
  const res = await apiFetch<{ forgotten?: number; devices?: unknown[] }>(`/api/telemetry/devices/${encodeURIComponent(group)}/${encodeURIComponent(node)}?${qs}`, { method: 'DELETE', throwOnError: false });
  if (!res.error) return { kind: 'done', count: res.data?.forgotten ?? res.data?.devices?.length ?? 1 };
  const code = res.errorDetail?.error_code;
  if (code === 'DEVICE_ONLINE' || res.errorDetail?.code === 409) {
    return { kind: 'online', message: res.error || 'It is online right now, so it would come straight back after being forgotten.' };
  }
  return { kind: 'error', message: explainTelemetryError({ status: res.errorDetail?.code, code, message: res.error }, 'delete') };
}

export async function forgetPreview(q: BulkQuery): Promise<{ result: BulkResult | null; error: string | null }> {
  const res = await apiFetch<BulkResult>('/api/telemetry/devices/forget', { method: 'POST', body: JSON.stringify({ ...q, dry_run: true }), throwOnError: false });
  if (res.error || !res.data) return { result: null, error: explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'load') };
  return { result: res.data, error: null };
}

// forgets in rounds until nothing that matches is left, telling the caller how far it got
export async function forgetAll(q: BulkQuery, onProgress: (done: number, remaining: number) => void, maxRounds = 50): Promise<{ forgotten: number; error: string | null }> {
  let total = 0;
  for (let i = 0; i < maxRounds; i++) {
    const res = await apiFetch<BulkResult>('/api/telemetry/devices/forget', { method: 'POST', body: JSON.stringify({ ...q, dry_run: false }), throwOnError: false });
    if (res.error || !res.data) {
      return { forgotten: total, error: explainTelemetryError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'delete') };
    }
    total += res.data.forgotten ?? 0;
    onProgress(total, res.data.remaining ?? 0);
    if (!res.data.remaining || !res.data.forgotten) break;
  }
  return { forgotten: total, error: null };
}

export function globProblem(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (/\s/.test(v)) return 'A pattern cannot contain spaces. Use * for any run of characters, like uat-*.';
  if (v.length > 120) return 'Keep the pattern under 120 characters.';
  return null;
}
