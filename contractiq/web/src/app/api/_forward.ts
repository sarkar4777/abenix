import type { NextRequest } from 'next/server';

/**
 * Headers to carry from the browser into the internal API.
 *
 * These route handlers run server-side, so nothing is forwarded unless it is
 * copied across explicitly. Omitting Authorization made every proxied call
 * unauthenticated: the upstream answered 401, the handler mirrored that status,
 * and the app's global fetch interceptor read it as an expired session and
 * signed the user out mid-page.
 */
export function forwardHeaders(req: NextRequest): HeadersInit {
  const out: Record<string, string> = {};
  const auth = req.headers.get('authorization');
  if (auth) out['Authorization'] = auth;
  const cookie = req.headers.get('cookie');
  if (cookie) out['Cookie'] = cookie;
  return out;
}
