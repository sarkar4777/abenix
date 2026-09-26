/**
 * fetch that carries the ContractIQ bearer token.
 *
 * The Next.js proxy routes under /api/contractiq-* run server-side and can only
 * forward an Authorization header the browser actually sent. The live-activity
 * pollers sent none, so every one of those calls came back 401.
 */
export function authHeader(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  try {
    const t = localStorage.getItem('contractiq_token');
    return t ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};
  }
}

export function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  return fetch(input, {
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...authHeader() },
  });
}
