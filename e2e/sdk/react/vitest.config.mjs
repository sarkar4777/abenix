import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  root: here('.'),
  esbuild: { jsx: 'automatic' },
  resolve: {
    alias: {
      '@abenix/sdk': here('../../../packages/sdk/js/dist/index.js'),
      '@abenix/react': here('../../../packages/sdk/react/src/index.ts'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['*.e2e.test.tsx'],
    testTimeout: 300_000,
    hookTimeout: 120_000,
    fileParallelism: false,
  },
});
