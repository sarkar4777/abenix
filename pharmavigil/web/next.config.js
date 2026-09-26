//
// Browser ↔ pharmavigil-api: same-origin via /api/pv/* rewrites, so the
// browser never makes a cross-origin call and CORS never enters the picture.
// PHARMAVIGIL_API_INTERNAL_URL picks the backend at build time.
//
const INTERNAL_API = process.env.PHARMAVIGIL_API_INTERNAL_URL || 'http://localhost:8007';

const nextConfig = {
  reactStrictMode: true,
  env: { NEXT_PUBLIC_API_URL: '' },
  // Assessment runs to several minutes; the default proxy timeout cuts the
  // SSE stream long before the pipeline lands.
  experimental: { proxyTimeout: 900_000 },
  async rewrites() {
    return [
      { source: '/api/pv/:path*', destination: `${INTERNAL_API}/api/pv/:path*` },
    ];
  },
};
module.exports = nextConfig;
