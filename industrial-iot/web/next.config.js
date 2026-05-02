//
// Architecture note:
// - Browser uses RELATIVE paths (/api/industrial-iot/..., /api/code-assets/...)
//   so it always hits the same origin
// - Next.js proxies those requests to INDUSTRIALIOT_API_INTERNAL_URL — the
//   standalone API pod — which then forwards platform-API calls
//   (/api/code-assets, /api/agents) on to abenix-api with the seeded
//   service-account API key. The browser never holds an Abenix token.
// - In dev:  INDUSTRIALIOT_API_INTERNAL_URL=http://localhost:8003
// - In k8s:  INDUSTRIALIOT_API_INTERNAL_URL=http://industrial-iot-api:8003
//
const INTERNAL_API = process.env.INDUSTRIALIOT_API_INTERNAL_URL || 'http://localhost:8003';

const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: '',
    NEXT_PUBLIC_ABENIX_WEB_URL: process.env.NEXT_PUBLIC_ABENIX_WEB_URL || '',
  },
  async rewrites() {
    return [
      {
        source: '/api/industrial-iot/:path*',
        destination: `${INTERNAL_API}/api/industrial-iot/:path*`,
      },
      // Platform-API passthrough: code-assets list/create/status polling.
      // The standalone API authenticates with the seeded
      // INDUSTRIALIOT_ABENIX_API_KEY before forwarding to abenix-api.
      // Two rules so we match both /api/code-assets (no path) and
      // /api/code-assets/<id> — :path* alone can be flaky for the empty case.
      {
        source: '/api/code-assets',
        destination: `${INTERNAL_API}/api/code-assets`,
      },
      {
        source: '/api/code-assets/:path*',
        destination: `${INTERNAL_API}/api/code-assets/:path*`,
      },
      // Same for agents (used to resolve pipeline ids in the UI).
      {
        source: '/api/agents',
        destination: `${INTERNAL_API}/api/agents`,
      },
      {
        source: '/api/agents/:path*',
        destination: `${INTERNAL_API}/api/agents/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
