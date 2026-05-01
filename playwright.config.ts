import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E configuration for Abenix.
 *
 * Supports two modes:
 *  1. Local dev: auto-starts web server (start.sh)
 *  2. K8s deployment: connect to existing services (deploy.sh local-runtime)
 *     Set USE_K8S=true to skip the webServer and connect directly.
 *
 * Environment variables:
 *   BASE_URL   — Frontend URL (default: http://localhost:3000)
 *   API_URL    — Backend API URL (default: http://localhost:8000)
 *   USE_K8S    — Skip webServer auto-start (default: false)
 *   CI         — Running in CI (retries=2, workers=1)
 */

const isK8s = !!process.env.USE_K8S;
const baseURL = process.env.BASE_URL || 'http://localhost:3000';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // Knowledge Engineering tests are serial by design
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 1, // Serial for stateful test suites
  reporter: [
    ['html', { open: 'never' }],
    ['list'],
    ...(process.env.CI ? [['github' as const]] : []),
  ],
  outputDir: './e2e/test-results',
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: process.env.CI ? 'on-first-retry' : 'off',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    // Optional: test on Firefox in CI
    ...(process.env.CI
      ? [
          {
            name: 'firefox',
            use: { ...devices['Desktop Firefox'] },
          },
        ]
      : []),
  ],
  // Only auto-start web server in local dev mode (not k8s)
  ...(isK8s
    ? {}
    : {
        webServer: {
          command: 'npm run dev --workspace=apps/web',
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }),
});
