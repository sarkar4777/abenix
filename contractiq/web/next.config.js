//
// Architecture note:
// - Browser uses RELATIVE paths (/api/contractiq/...) so it always hits the same origin
// - Next.js proxies those requests to CONTRACTIQ_API_INTERNAL_URL (server-side env var)
// - In dev: CONTRACTIQ_API_INTERNAL_URL=http://localhost:8001
// - In k8s: CONTRACTIQ_API_INTERNAL_URL=http://contractiq-api:8001 (cluster DNS)
//
// This avoids the "browser can't reach cluster DNS" problem entirely.
//
const INTERNAL_API = process.env.CONTRACTIQ_API_INTERNAL_URL || 'http://localhost:8001';

const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: '',
  },
  // Long-running LLM calls (valuation, simulate, generate-endur-json,
  // force-majeure scan, ...) regularly take 30-180s. Default 30s proxy
  // timeout was returning plain-text "Internal Server Error" to the
  // browser, which then failed JSON.parse with "Unexpected token 'I'".
  experimental: {
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [
      {
        source: '/api/contractiq/:path*',
        destination: `${INTERNAL_API}/api/contractiq/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
