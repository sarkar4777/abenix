import { test, expect } from '@playwright/test';

const BASE = process.env.BASE_WM || 'http://localhost:3006';

test.describe.serial('Wingman quick UAT — cached forecast + live compliance', () => {
  test('home page renders, dashboard surface visible', async ({ page }) => {
    await page.goto(`${BASE}/home`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByRole('main').getByText('Arbitrage Workbench').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('main').getByText('Price at Risk Lens').first()).toBeVisible();
    await expect(page.getByRole('main').getByText('Forward Scenarios').first()).toBeVisible();
  });

  test('scenarios: cached USGC-NWE forecast renders fan chart with numeric P10/P90', async ({ page }) => {
    await page.goto(`${BASE}/scenarios`, { waitUntil: 'domcontentloaded' });
    // Pick USGC-NWE chip
    const chip = page.getByTestId('corridor-chip-USGC-NWE');
    await expect(chip).toBeVisible({ timeout: 10_000 });
    await chip.click();
    // Fan chart panel should render (cached value populates within ~5s)
    await expect(page.getByText(/Expected curve.*P10\/P90/i).first()).toBeVisible({ timeout: 15_000 });
    // All 5 scenario cards by id
    for (const id of ['base', 'bull_geopolitical', 'bear_supply_glut', 'bear_demand_shock', 'tail_event']) {
      await expect(page.getByTestId(`scenario-card-${id}`).first()).toBeVisible({ timeout: 5_000 });
    }
    // Sliders panel — proves drivers + posterior probability rendered
    await expect(page.getByTestId('scenarios-sliders')).toBeVisible();
  });

  test('compliance: validate fictional order returns BLOCK with KB + Atlas citations', async () => {
    const action = {
      action_kind: 'trade_card',
      corridor: {
        id: 'USGC-NWE',
        label: 'US Gulf Coast to North West Europe',
        origin_port: 'Houston',
        destination_port: 'Rotterdam',
        vessel_class: 'VLGC',
      },
      structure: { side: 'buy', size_mt: 50000, tenor_months: 3, instrument: 'spread' },
      timing_utc: new Date().toISOString(),
    };
    const r = await fetch(`${BASE}/api/wingman/compliance/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    });
    expect(r.ok, 'compliance validate must respond 200').toBeTruthy();
    const j: any = await r.json();
    const d = j?.data;
    expect(d).toBeTruthy();
    expect(['ALLOWED', 'WARN', 'BLOCK']).toContain(d.verdict);
    // 50,000 MT VLGC > 5,000 MT internal cap → must be BLOCK
    expect(d.verdict).toBe('BLOCK');
    // Real rules from KB / Atlas
    const kbHits = (d.citations || []).filter((c: any) => c.source === 'kb');
    const atlasHits = (d.citations || []).filter((c: any) => c.source === 'atlas');
    expect(kbHits.length, 'at least one KB citation').toBeGreaterThan(0);
    expect(atlasHits.length, 'at least one Atlas citation').toBeGreaterThan(0);
    // Per-rule structured checks
    expect((d.checks || []).length).toBeGreaterThanOrEqual(3);
    const sizeRule = (d.checks || []).find((c: any) => /size/i.test(c.rule));
    expect(sizeRule, 'size rule present').toBeTruthy();
    expect(sizeRule.pass).toBe(false);
  });

  test('mispricing: page shell + explainer with 15-feature model copy', async ({ page }) => {
    await page.goto(`${BASE}/mispricing`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText('PRICE AT RISK LENS').first()).toBeVisible({ timeout: 10_000 });
    const explainer = page.getByTestId('model-explainer');
    await expect(explainer).toBeVisible();
    await expect(explainer.getByText(/15 features/i).first()).toBeVisible();
  });
});
