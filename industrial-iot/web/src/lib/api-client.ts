/**
 * Minimal apiFetch for the standalone Industrial-IoT web.
 *
 * Browser always hits relative paths; Next.js rewrites proxy `/api/code-assets/*`
 * through to the Abenix API (see next.config.js). The IoT API pod owns
 * the Abenix service-account credential, so no token leaves the server.
 */

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  meta: Record<string, unknown> | null;
}

interface FetchOptions extends Omit<RequestInit, 'headers'> {
  headers?: Record<string, string>;
  silent?: boolean;
}

export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {},
): Promise<ApiResponse<T>> {
  const { silent: _silent, ...fetchOpts } = options;
  const headers: Record<string, string> = { ...fetchOpts.headers };
  if (fetchOpts.body && typeof fetchOpts.body === 'string') {
    headers['Content-Type'] = 'application/json';
  }
  try {
    const res = await fetch(path, { ...fetchOpts, headers });
    const json = await res.json().catch(() => ({}));
    return {
      data: json.data ?? null,
      error: json.error?.message ?? json.error ?? (res.ok ? null : `HTTP ${res.status}`),
      meta: json.meta ?? null,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Network error';
    return { data: null, error: msg, meta: null };
  }
}
