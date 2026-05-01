const path = require('path');

const nextConfig = {
  output: 'standalone',
  // Required for npm workspaces — tells Next.js to trace dependencies from the monorepo root
  // In Docker, __dirname is /app/apps/web, so ../../ = /app (the WORKDIR)
  outputFileTracingRoot: path.join(__dirname, '../..'),
  transpilePackages: ['@abenix/shared'],
};

module.exports = nextConfig;
