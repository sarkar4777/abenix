//
// Architecture note:
// - Browser uses RELATIVE paths (/api/industrial-iot/...) so it always hits the same origin
// - Next.js proxies those requests to INDUSTRIALIOT_API_INTERNAL_URL (server-side env var)
// - In dev:  INDUSTRIALIOT_API_INTERNAL_URL=http://localhost:8003
// - In k8s:  INDUSTRIALIOT_API_INTERNAL_URL=http://industrial-iot-api:8003 (cluster DNS)
//
// All Abenix calls still go through the `abenix_sdk` module in our thin
// backend, so the browser never holds an Abenix token.
//
const INTERNAL_API = process.env.INDUSTRIALIOT_API_INTERNAL_URL || 'http://localhost:8003';
// `/api/code-assets/*` hits the core Abenix API directly — that's where
// the upload-and-deploy flow for pump DSP / RUL / cold-chain assets lives.
// In k8s this should be cluster DNS (http://abenix-api:8000); locally
// it's http://localhost:8000.
const ABENIX_API = process.env.ABENIX_API_URL || 'http://localhost:8000';

const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: '',
  },
  async rewrites() {
    return [
      {
        source: '/api/industrial-iot/:path*',
        destination: `${INTERNAL_API}/api/industrial-iot/:path*`,
      },
      {
        source: '/api/code-assets/:path*',
        destination: `${ABENIX_API}/api/code-assets/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
