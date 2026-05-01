const INTERNAL_API = process.env.SAUDITOURISM_API_INTERNAL_URL || 'http://localhost:8002';

const nextConfig = {
  reactStrictMode: true,
  env: {
    // In dev: browser calls API directly (no proxy timeout issues)
    // In k8s: set to '' so browser uses relative URLs → Next.js proxy → cluster DNS
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8002',
  },
  async rewrites() {
    return [
      {
        source: '/api/st/:path*',
        destination: `${INTERNAL_API}/api/st/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
