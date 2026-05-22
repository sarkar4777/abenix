
const DEFAULT_TIMEOUT_MS = 10 * 60 * 1000; // 10 min — long-running LLM calls

export type ApiResult<T = any> = {
  ok: boolean;
  status: number;
  data?: T;
  error?: string;
};

export async function safeJson<T = any>(r: Response): Promise<ApiResult<T>> {
  const text = await r.text().catch(() => '');
  if (!text) {
    return r.ok
      ? { ok: true, status: r.status }
      : { ok: false, status: r.status, error: r.statusText || `HTTP ${r.status}` };
  }
  try {
    const parsed = JSON.parse(text);
    if (!r.ok) {
      const detail =
        parsed?.detail ||
        parsed?.error?.message ||
        parsed?.error ||
        parsed?.message ||
        `HTTP ${r.status}`;
      return { ok: false, status: r.status, data: parsed, error: String(detail) };
    }
    if (parsed?.error) {
      const m = parsed.error?.message || parsed.error;
      return { ok: false, status: r.status, data: parsed, error: typeof m === 'string' ? m : 'Server error' };
    }
    return { ok: true, status: r.status, data: parsed };
  } catch {
    const snippet = text.length > 200 ? text.slice(0, 200) + '…' : text;
    if (r.ok) return { ok: false, status: r.status, error: `Server returned non-JSON: ${snippet}` };
    return {
      ok: false,
      status: r.status,
      error: r.status >= 500
        ? `Server error (HTTP ${r.status}). The request may have timed out — please retry.`
        : `HTTP ${r.status}: ${snippet}`,
    };
  }
}

export async function apiFetch<T = any>(
  url: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<ApiResult<T>> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...rest } = init;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  if (callerSignal) {
    if (callerSignal.aborted) ctrl.abort();
    else callerSignal.addEventListener('abort', () => ctrl.abort(), { once: true });
  }
  try {
    const r = await fetch(url, { ...rest, signal: ctrl.signal });
    return await safeJson<T>(r);
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      return { ok: false, status: 0, error: 'Request timed out — the server is taking longer than expected.' };
    }
    return { ok: false, status: 0, error: e?.message || 'Network error' };
  } finally {
    clearTimeout(timer);
  }
}
