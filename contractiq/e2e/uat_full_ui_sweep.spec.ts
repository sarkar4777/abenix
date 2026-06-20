import { test, expect, type Page } from '@playwright/test';

const BASE = process.env.BASE_URL || 'http://localhost:3001';
const API = process.env.API_URL || 'http://localhost:8001';
const EMAIL = process.env.CIQ_EMAIL || 'test@contractiq.com';
const PASSWORD = process.env.CIQ_PASSWORD || 'TestPass123!';

async function login(page: Page) {
  const r = await page.request.post(`${API}/api/contractiq/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  const body = await r.json();
  const token = body?.data?.access_token ?? body?.access_token;
  const user = body?.data?.user ?? body?.user;
  await page.addInitScript(([tok, usr]: [string, any]) => {
    localStorage.setItem('contractiq_token', tok);
    if (usr) localStorage.setItem('contractiq_user', JSON.stringify(usr));
  }, [token, user]);
}

// All wired user-facing surfaces. Each entry has the route and a quick
// "page is healthy" assertion (h1 substring or a visible element).
const ROUTES: { path: string; expect_text?: RegExp; quick_action?: 'expand_explainer' }[] = [
  // Public/landing
  { path: '/', expect_text: /Upload your PPA|sign in/i },

  // Core
  { path: '/dashboard', expect_text: /Portfolio Analytics|Dashboard/i, quick_action: 'expand_explainer' },
  { path: '/contracts', expect_text: /My Contracts|Contracts/i, quick_action: 'expand_explainer' },
  { path: '/upload', expect_text: /Upload Contract|Upload/i, quick_action: 'expand_explainer' },
  { path: '/help', expect_text: /Help|Agent Atlas/i, quick_action: 'expand_explainer' },
  { path: '/chat', expect_text: /Cross-Contract|Chat/i, quick_action: 'expand_explainer' },

  // Commodities — selector + 7 variants
  { path: '/commodities/forward', expect_text: /Forward fair-value/i, quick_action: 'expand_explainer' },
  { path: '/commodities/forward?commodity=pipeline_gas', expect_text: /Pipeline Gas/i },
  { path: '/commodities/forward?commodity=lng', expect_text: /LNG/i },
  { path: '/commodities/forward?commodity=power', expect_text: /Power/i },
  { path: '/commodities/forward?commodity=carbon', expect_text: /Carbon|EUA/i },
  { path: '/commodities/forward?commodity=crude', expect_text: /Crude|Brent/i },
  { path: '/commodities/forward?commodity=refined', expect_text: /Refined/i },
  { path: '/commodities/forward?commodity=coal', expect_text: /Coal/i },

  // Legacy redirect commodity hubs (should resolve to forward selector)
  { path: '/commodities/gas', expect_text: /(Forward|Pipeline)/i },
  { path: '/commodities/lng', expect_text: /(Forward|LNG)/i },
  { path: '/commodities/power', expect_text: /(Forward|Power)/i },

  // Price engine
  { path: '/price-engine', expect_text: /Price Engine|Forward/i, quick_action: 'expand_explainer' },

  // Risk
  { path: '/risk', expect_text: /Market Risk|VaR/i, quick_action: 'expand_explainer' },

  // Credit risk
  { path: '/credit-risk', expect_text: /Credit Risk|Counterparty/i, quick_action: 'expand_explainer' },
  { path: '/credit-risk/kyc', expect_text: /KYC/i, quick_action: 'expand_explainer' },
  { path: '/credit-risk/kyc/new', expect_text: /New KYC|Counterparty/i, quick_action: 'expand_explainer' },

  // Insights
  { path: '/insights', expect_text: /Insights/i, quick_action: 'expand_explainer' },
  { path: '/insights/briefing', expect_text: /Briefing|Executive/i, quick_action: 'expand_explainer' },
  { path: '/insights/anomalies', expect_text: /Anomalies/i, quick_action: 'expand_explainer' },
  { path: '/insights/stress-test', expect_text: /Stress/i, quick_action: 'expand_explainer' },
  { path: '/insights/benchmark', expect_text: /Benchmark/i, quick_action: 'expand_explainer' },
  { path: '/insights/renewals', expect_text: /Renewal/i, quick_action: 'expand_explainer' },
  { path: '/insights/force-majeure', expect_text: /Force Majeure/i, quick_action: 'expand_explainer' },
  { path: '/insights/hedge', expect_text: /Hedge/i, quick_action: 'expand_explainer' },
  { path: '/insights/version-diff', expect_text: /Version|Diff/i, quick_action: 'expand_explainer' },
  { path: '/insights/reconciliation', expect_text: /Reconcil/i, quick_action: 'expand_explainer' },
  { path: '/insights/families', expect_text: /Famil/i, quick_action: 'expand_explainer' },

  // Valuation & forecasting
  { path: '/valuation', expect_text: /Valuation/i, quick_action: 'expand_explainer' },
  { path: '/forecaster', expect_text: /Forecaster|Offtake/i, quick_action: 'expand_explainer' },
  { path: '/recommendations', expect_text: /Recommend/i, quick_action: 'expand_explainer' },

  // Analyst surfaces
  { path: '/workbench', expect_text: /Workbench/i, quick_action: 'expand_explainer' },
  { path: '/data-fabric', expect_text: /Data Fabric/i, quick_action: 'expand_explainer' },
  { path: '/model-performance', expect_text: /Model Performance|Backtest/i, quick_action: 'expand_explainer' },

  // Comparison / utility
  { path: '/compare', expect_text: /Compar/i, quick_action: 'expand_explainer' },
  { path: '/simulations', expect_text: /Simulation/i, quick_action: 'expand_explainer' },
  { path: '/timeline', expect_text: /Timeline/i, quick_action: 'expand_explainer' },
  { path: '/clauses', expect_text: /Clause/i, quick_action: 'expand_explainer' },
  { path: '/deal-clusters', expect_text: /Deal|Cluster/i, quick_action: 'expand_explainer' },
  { path: '/features', expect_text: /Features|Catalog/i, quick_action: 'expand_explainer' },

  // Metals suite
  { path: '/metals', expect_text: /Metals/i, quick_action: 'expand_explainer' },
  { path: '/metals/compliance', expect_text: /Compliance/i, quick_action: 'expand_explainer' },
  { path: '/metals/disputes', expect_text: /Dispute/i, quick_action: 'expand_explainer' },
  { path: '/metals/extract', expect_text: /Extract/i, quick_action: 'expand_explainer' },
  { path: '/metals/loco', expect_text: /Loco/i, quick_action: 'expand_explainer' },
  { path: '/metals/refiners', expect_text: /Refiner/i, quick_action: 'expand_explainer' },
  { path: '/metals/sourcing', expect_text: /Sourcing/i, quick_action: 'expand_explainer' },

  // Market
  { path: '/market', expect_text: /Market/i, quick_action: 'expand_explainer' },
];

test.describe('Full UI sweep — local stack', () => {
  for (const r of ROUTES) {
    test(`render: ${r.path}`, async ({ page }) => {
      await login(page);

      const errors: string[] = [];
      page.on('pageerror', (err) => errors.push(err.message));
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(`[console] ${msg.text()}`);
      });

      const resp = await page.goto(`${BASE}${r.path}`, { waitUntil: 'domcontentloaded' });
      expect(resp?.status() ?? 0).toBeLessThan(500);

      // Wait for body text
      if (r.expect_text) {
        await expect(page.locator('body')).toContainText(r.expect_text, { timeout: 15000 });
      } else {
        await expect(page.locator('h1, h2').first()).toBeVisible({ timeout: 15000 });
      }

      // Try to expand the explainer if the page has one
      if (r.quick_action === 'expand_explainer') {
        const trigger = page.getByRole('button', { name: /What is this page/i }).first();
        const visible = await trigger.isVisible({ timeout: 8000 }).catch(() => false);
        if (visible) {
          await trigger.click();
          const card = page.getByTestId('page-explainer-card');
          // Card should appear, but if the route has no explanation entry it'll silent no-op
          await card.waitFor({ state: 'visible', timeout: 6000 }).catch(() => {});
        }
      }

      // Filter ignorable console noise from third-party libs
      const real = errors.filter(e =>
        !/ResizeObserver|hydration|Failed to fetch dynamically imported module/i.test(e) &&
        !/favicon/i.test(e)
      );
      if (real.length) {
        console.log(`[${r.path}] errors:`, real.slice(0, 3));
      }
    });
  }
});
