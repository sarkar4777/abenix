// Wingman web — port 3006. Browser uses relative /api/wingman/* paths;
// Next.js proxies them to WINGMAN_API_INTERNAL_URL (the wingman-api pod).
// Same architecture as industrial-iot/contractiq.
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
      // Sidebar fires /api/auth/me to fill the user footer — Wingman has no
      // user DB, so the wingman-api side returns a stub demo-trader identity.
      {
        source: '/api/auth/:path*',
        destination: `${INTERNAL_API}/api/auth/:path*`,
      },
      // Code-asset registry probes (NotificationBell + future builder palette)
      // land at /api/code-assets. Forward to wingman-api which fans out to
      // Abenix through the SDK so the call carries the demo-trader subject.
      // Without this the request misses every rewrite and the browser logs a
      // 502 on home-page mount.
      {
        source: '/api/code-assets',
        destination: `${INTERNAL_API}/api/code-assets`,
      },
      {
        source: '/api/code-assets/:path*',
        destination: `${INTERNAL_API}/api/code-assets/:path*`,
      },
    ];
  },
  async redirects() {
    // Compliance Lens lives inside the Mispricing trade card. Browsers preserve
    // the #compliance hash through a same-origin 308, so old bookmarks still land
    // on the right section without the client-side flash.
    return [
      {
        source: '/compliance',
        destination: '/mispricing#compliance',
        permanent: true,
      },
    ];
  },
};

module.exports = nextConfig;
