// Wingman web — port 3006. Browser uses relative /api/wingman/* paths;
// Next.js proxies them to WINGMAN_API_INTERNAL_URL (the wingman-api pod).
// Same architecture as industrial-iot/example_app.
const INTERNAL_API = process.env.WINGMAN_API_INTERNAL_URL || 'http://localhost:8006';

const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: '',
  },
  experimental: {
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [
      {
        source: '/api/wingman/:path*',
        destination: `${INTERNAL_API}/api/wingman/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
