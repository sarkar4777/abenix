export interface OpsResult {
  status: string;
  snapshot?: Record<string, unknown> | null;
  error_message?: string | null;
}

const DONE = new Set(['completed', 'succeeded']);
const FAILED = new Set(['failed', 'error', 'cancelled']);

// polls the run until it ends, so the caller shows an answer or a reason and never nothing
export async function followRun(
  executionId: string,
  { intervalMs = 2500, maxWaitMs = 300_000, maxMisses = 5, get = fetch as typeof fetch, sleep = (ms: number) => new Promise((r) => setTimeout(r, ms)), stopped = (() => false) as () => boolean } = {},
): Promise<{ snapshot?: Record<string, unknown> | null; error?: string }> {
  let misses = 0;
  for (let waited = 0; waited < maxWaitMs && !stopped(); waited += intervalMs) {
    await sleep(intervalMs);
    try {
      const r = await get(`/api/wingman/ops/result/${executionId}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data: OpsResult = (await r.json()).data;
      misses = 0;
      if (DONE.has(data.status)) return { snapshot: data.snapshot };
      if (FAILED.has(data.status)) return { error: data.error_message || `The ops monitor ended as ${data.status}.` };
    } catch (e) {
      misses += 1;
      if (misses >= maxMisses) return { error: `Could not read the ops monitor run, ${e instanceof Error ? e.message : e}.` };
    }
  }
  return stopped() ? {} : { error: 'The ops monitor is still running after 5 minutes. The page keeps its last snapshot.' };
}
