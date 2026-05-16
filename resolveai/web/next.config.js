//
// Browser ↔ ResolveAI-api: same-origin via /api/resolveai/* rewrites.
// RESOLVEAI_API_INTERNAL_URL picks the backend at build time.
//
const INTERNAL_API = process.env.RESOLVEAI_API_INTERNAL_URL || 'http://localhost:8004';

const nextConfig = {
  reactStrictMode: true,
  env: { NEXT_PUBLIC_API_URL: '' },
  experimental: { proxyTimeout: 300_000 },
  async rewrites() {
    return [
      { source: '/api/resolveai/:path*', destination: `${INTERNAL_API}/api/resolveai/:path*` },
    ];
  },
};
module.exports = nextConfig;
