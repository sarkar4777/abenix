//
// Browser ↔ quoteiq-api: same-origin via /api/qq/* rewrites, so the browser
// never makes a cross-origin call and CORS never enters the picture.
// QUOTEIQ_API_INTERNAL_URL picks the backend at build time.
//
const INTERNAL_API = process.env.QUOTEIQ_API_INTERNAL_URL || 'http://localhost:8008';

const nextConfig = {
  reactStrictMode: true,
  env: { NEXT_PUBLIC_API_URL: '' },
  async rewrites() {
    return [
      { source: '/api/qq/:path*', destination: `${INTERNAL_API}/api/qq/:path*` },
    ];
  },
};
module.exports = nextConfig;
