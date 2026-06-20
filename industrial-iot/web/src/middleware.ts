// Inject the IIOT web-proxy secret on every request that the
// next.config.js rewrites forward to the standalone API's platform-API
// passthrough (/api/code-assets, /api/agents, /api/connectors). The API
// pod rejects any of those paths if the header is missing or wrong, so
// arbitrary in-cluster callers can no longer impersonate the standalone
// tenant. Middleware runs server-side only, so the secret stays out of
// the browser bundle.
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const SECRET = process.env.INDUSTRIALIOT_WEB_PROXY_SECRET || '';

export function middleware(request: NextRequest) {
  if (!SECRET) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.set('X-IIOT-Web-Secret', SECRET);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    '/api/code-assets',
    '/api/code-assets/:path*',
    '/api/agents',
    '/api/agents/:path*',
    '/api/connectors',
    '/api/connectors/:path*',
  ],
};
