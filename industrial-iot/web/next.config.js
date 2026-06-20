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
  // ValueEdge / FieldEdge / BedROCC pipelines hit the agent runtime
  // sequentially through 4-9 LLM nodes — total wall time runs 2-5 min.
  // Default 30s proxy timeout was returning HTTP 500 to the browser
  // mid-pipeline; the standalone API itself caps wait at 240s. Match the
  // contractiq config (600s) so the long-running paths complete.
  experimental: {
    proxyTimeout: 600_000,
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
      // Connectors — routed through the standalone API so the browser
      // never holds the platform API key. Approvals are deliberately
      // not proxied: HITL approvals carry business decisions and must
      // never be readable through an anonymous standalone passthrough.
      {
        source: '/api/connectors',
        destination: `${INTERNAL_API}/api/connectors`,
      },
      {
        source: '/api/connectors/:path*',
        destination: `${INTERNAL_API}/api/connectors/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
