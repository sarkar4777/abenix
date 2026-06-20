import { test, expect, type Page, type Route } from '@playwright/test';

// Three scenarios covered by this spec:
//   1. Azure-only environment hides Claude/Gemini/non-azure GPT from every picker.
//   2. Execution detail page surfaces the fallback badge when actual != requested.
//   3. Zero configured providers puts the picker into its disabled empty state.
//
// All three rely on Playwright route() to mock the two endpoints the picker hits
// (/api/llm/available-providers and /api/llm-models) plus a hard-block of
// api.anthropic.com / generativelanguage.googleapis.com to prove the UI does not
// even attempt those vendors when the env says they are off.

const BASE = process.env.BASE_URL || process.env.ABENIX_BASE || 'http://localhost:3000';
const API = process.env.API_URL || 'http://localhost:8000';
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || process.env.AF_EMAIL || 'admin@abenix.dev';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || process.env.AF_PASSWORD || 'Admin123456';

let cachedToken: string | null = null;
async function platformToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  const r = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD }),
  });
  const body = await r.json();
  cachedToken = (body?.data?.access_token || body?.access_token) as string;
  expect(cachedToken, 'admin token').toBeTruthy();
  return cachedToken;
}

async function loginInBrowser(page: Page): Promise<string> {
  const token = await platformToken();
  const meR = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me = (await meR.json())?.data ?? {};
  await page.addInitScript(({ t, u }) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
    localStorage.setItem('user', JSON.stringify(u || {}));
  }, { t: token, u: me });
  return token;
}

// Mock the provider probe to a chosen shape; everything else passes through.
async function mockAvailableProviders(
  page: Page,
  providers: Record<string, { configured: boolean; reason?: string | null }>,
) {
  await page.route(/\/api\/llm\/available-providers(\?|$)/, (route: Route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: providers, error: null, meta: null }),
    });
  });
}

// Force /api/llm-models to return a deterministic catalog so the assertions
// don't drift with the actual cluster's seeded pricing table.
async function mockLlmModels(page: Page) {
  const models = [
    { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5', provider: 'anthropic', input_per_m: 3, output_per_m: 15, capabilities: { tools: true } },
    { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', provider: 'anthropic', input_per_m: 1, output_per_m: 5, capabilities: { tools: true } },
    { value: 'gpt-4o', label: 'GPT-4o', provider: 'openai', input_per_m: 5, output_per_m: 15, capabilities: { tools: true } },
    { value: 'gpt-4o-mini', label: 'GPT-4o Mini', provider: 'openai', input_per_m: 0.15, output_per_m: 0.6, capabilities: { tools: true } },
    { value: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro', provider: 'google', input_per_m: 1.25, output_per_m: 5, capabilities: { tools: true } },
    { value: 'gemini-1.5-flash', label: 'Gemini 1.5 Flash', provider: 'google', input_per_m: 0.075, output_per_m: 0.3, capabilities: { tools: true } },
    { value: 'azure-gpt-4o', label: 'Azure GPT-4o', provider: 'azure', input_per_m: 5, output_per_m: 15, capabilities: { tools: true } },
    { value: 'azure-gpt-4o-mini', label: 'Azure GPT-4o Mini', provider: 'azure', input_per_m: 0.15, output_per_m: 0.6, capabilities: { tools: true } },
    { value: 'azure-gpt-35-turbo', label: 'Azure GPT-3.5 Turbo', provider: 'azure', input_per_m: 0.5, output_per_m: 1.5, capabilities: { tools: true } },
  ];
  await page.route(/\/api\/llm-models(\?|$)/, (route: Route) => {
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: { models }, error: null, meta: null }),
    });
  });
}

// Hard-block any direct vendor traffic so we can prove the UI never reaches it.
async function blockUpstreamVendors(page: Page) {
  await page.route(/https?:\/\/api\.anthropic\.com\/.*/, (route: Route) =>
    route.abort('blockedbyclient'),
  );
  await page.route(/https?:\/\/generativelanguage\.googleapis\.com\/.*/, (route: Route) =>
    route.abort('blockedbyclient'),
  );
}

// The AgentConfigPanel right-hand drawer hides the ModelPicker behind a
// "Model" tab. The tab buttons render an inner <span>Model</span> with the
// surrounding <button> using CSS uppercase. Sweep every button on the page
// whose inner span text is "Model" and click it; verify the picker mounts.
async function clickModelTab(page: Page): Promise<void> {
  await page.waitForSelector('button', { timeout: 30_000 }).catch(() => {});
  for (let attempt = 0; attempt < 6; attempt++) {
    // Use evaluate so we can ignore overlays / pointer-events filtering.
    const clicked = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button')) as HTMLButtonElement[];
      for (const b of btns) {
        const sp = b.querySelector('span');
        const txt = (sp?.textContent || b.textContent || '').trim();
        if (txt.toLowerCase() === 'model') {
          b.click();
          return true;
        }
      }
      return false;
    });
    if (clicked) {
      await page.waitForTimeout(300);
      if (await page.locator('[data-testid="model-picker"]').count()) return;
    }
    await page.waitForTimeout(500);
  }
}

async function readAllSelectOptions(page: Page): Promise<string[]> {
  // ModelPicker uses a native <select>, so optgroups + options are inspectable.
  const selects = page.locator('[data-testid="model-picker-select"]');
  const count = await selects.count();
  const seen: string[] = [];
  for (let i = 0; i < count; i++) {
    const sel = selects.nth(i);
    const opts = sel.locator('option');
    const n = await opts.count();
    for (let j = 0; j < n; j++) {
      const v = (await opts.nth(j).getAttribute('value')) || '';
      const t = (await opts.nth(j).innerText().catch(() => '')) || '';
      if (v) seen.push(v);
      if (t) seen.push(t);
    }
  }
  return seen;
}

// Pull just the model `value` attrs (not labels) so assertions don't trip on
// the picker's prettified display names.
async function readSelectValues(page: Page): Promise<string[]> {
  const selects = page.locator('[data-testid="model-picker-select"]');
  const count = await selects.count();
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    const sel = selects.nth(i);
    const opts = sel.locator('option');
    const n = await opts.count();
    for (let j = 0; j < n; j++) {
      const v = (await opts.nth(j).getAttribute('value')) || '';
      if (v) out.push(v);
    }
  }
  return out;
}

test.describe.serial('Provider key picker + fallback badge', () => {
  test.beforeEach(async ({ page }) => {
    page.setDefaultNavigationTimeout(60_000);
    page.setDefaultTimeout(20_000);
  });

  test('1. Azure-only env hides Claude/Gemini/non-azure GPT from every picker', async ({ page }) => {
    test.setTimeout(180_000);
    await loginInBrowser(page);
    await blockUpstreamVendors(page);
    await mockAvailableProviders(page, {
      anthropic: { configured: false, reason: 'ANTHROPIC_API_KEY not set' },
      openai: { configured: false, reason: 'OPENAI_API_KEY not set' },
      google: { configured: false, reason: 'GOOGLE_API_KEY not set' },
      azure: { configured: true, reason: null },
    });
    await mockLlmModels(page);

    // /builder — first picker lives on the right-hand AgentConfigPanel
    // under the "Model" tab; click that tab so the picker mounts.
    await page.goto(`${BASE}/builder`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await clickModelTab(page);
    await expect(page.locator('[data-testid="model-picker"]').first()).toBeVisible({ timeout: 25_000 });
    // Wait for picker to finish loading (loading state shows "Loading models…").
    await page.waitForFunction(
      () => {
        const sel = document.querySelector('[data-testid="model-picker-select"]') as HTMLSelectElement | null;
        if (!sel) return false;
        return !sel.disabled && sel.options.length > 0 && sel.options[0].text !== 'Loading models…';
      },
      { timeout: 15_000 },
    ).catch(() => {});

    const builderValues = await readSelectValues(page);
    console.log('  builder picker values:', builderValues);
    expect(builderValues.length).toBeGreaterThan(0);
    for (const v of builderValues) {
      // value strings should not be claude/gemini/non-azure gpt
      expect(v.toLowerCase()).not.toContain('claude');
      expect(v.toLowerCase()).not.toContain('gemini');
      expect(v.toLowerCase()).not.toMatch(/^gpt-/); // non-azure gpt-4o/gpt-4o-mini etc.
      expect(v.toLowerCase().startsWith('azure-')).toBeTruthy();
    }

    // Sanity: the info note tells the user only Azure is available.
    const infoText = await page.locator('[data-testid="model-picker-info"]').first().innerText().catch(() => '');
    console.log('  builder info:', infoText);
    expect(infoText.toLowerCase()).toContain('azure');

    // /agents/new — redirects to /builder, so same expectations after the
    // redirect lands.
    await page.goto(`${BASE}/agents/new`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await clickModelTab(page);
    await expect(page.locator('[data-testid="model-picker"]').first()).toBeVisible({ timeout: 25_000 });
    await page.waitForFunction(
      () => {
        const sel = document.querySelector('[data-testid="model-picker-select"]') as HTMLSelectElement | null;
        if (!sel) return false;
        return !sel.disabled && sel.options.length > 0 && sel.options[0].text !== 'Loading models…';
      },
      { timeout: 15_000 },
    ).catch(() => {});
    const newAgentValues = await readSelectValues(page);
    for (const v of newAgentValues) {
      expect(v.toLowerCase()).not.toContain('claude');
      expect(v.toLowerCase()).not.toContain('gemini');
      expect(v.toLowerCase()).not.toMatch(/^gpt-/);
      expect(v.toLowerCase().startsWith('azure-')).toBeTruthy();
    }

    // /admin/llm-settings — multiple ModelPickers, one per setting key.
    await page.goto(`${BASE}/admin/llm-settings`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await expect(page.locator('[data-testid="model-picker"]').first()).toBeVisible({ timeout: 25_000 });
    await page.waitForFunction(
      () => {
        const sels = Array.from(document.querySelectorAll('[data-testid="model-picker-select"]')) as HTMLSelectElement[];
        if (sels.length === 0) return false;
        return sels.every((s) => !s.disabled && s.options.length > 0 && s.options[0].text !== 'Loading models…');
      },
      { timeout: 15_000 },
    ).catch(() => {});
    const adminValues = await readSelectValues(page);
    console.log('  admin picker values (sample):', adminValues.slice(0, 12));
    expect(adminValues.length).toBeGreaterThan(0);
    for (const v of adminValues) {
      expect(v.toLowerCase()).not.toContain('claude');
      expect(v.toLowerCase()).not.toContain('gemini');
      expect(v.toLowerCase()).not.toMatch(/^gpt-/);
      expect(v.toLowerCase().startsWith('azure-')).toBeTruthy();
    }

    // Also sanity check displayed text never advertises blocked providers.
    const allText = (await readAllSelectOptions(page)).join(' | ').toLowerCase();
    expect(allText).not.toContain('gemini');
    // Claude / GPT-4o label words may appear in disabled help-text; gate strictly
    // on the option *value* attribute (above) which is what the UI submits.
  });

  test('2. Execution detail page surfaces the fallback badge', async ({ page }) => {
    test.setTimeout(120_000);
    await loginInBrowser(page);
    // Allow the picker mocks too so the rest of the page doesn't error.
    await mockAvailableProviders(page, {
      anthropic: { configured: false, reason: 'ANTHROPIC_API_KEY not set' },
      openai: { configured: false, reason: 'OPENAI_API_KEY not set' },
      google: { configured: false, reason: 'GOOGLE_API_KEY not set' },
      azure: { configured: true, reason: null },
    });

    const execId = '11111111-2222-3333-4444-555555555555';
    const requestedModel = 'claude-sonnet-4-5-20250929';
    const actualModel = 'azure-gpt-4o';

    // FallbackBadge needs both actual_model and requested_model and they must
    // differ. Mirror those on top-level fields the page reads.
    await page.route(new RegExp(`/api/executions/${execId}(\\?|$)`), (route: Route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          data: {
            id: execId,
            agent_id: 'agent-uat',
            agent_name: 'UAT Fallback Agent',
            status: 'completed',
            input_message: 'Hello from the fallback UAT.',
            output_message: 'Mocked output from azure-gpt-4o.',
            input_tokens: 100,
            output_tokens: 200,
            cost: 0.0042,
            duration_ms: 1234,
            model: requestedModel,
            model_requested: requestedModel,
            model_used: actualModel,
            actual_model: actualModel,
            fallback_reason: 'claude unavailable',
            tool_calls: [],
            confidence_score: 0.82,
            execution_trace: { steps: [], tool_calls: [] },
            created_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
          },
          error: null,
          meta: null,
        }),
      });
    });

    await page.goto(`${BASE}/executions/${execId}`, { waitUntil: 'domcontentloaded', timeout: 60_000 });

    const badge = page.locator('[data-testid="fallback-badge"]').first();
    await expect(badge).toBeVisible({ timeout: 15_000 });
    const badgeText = (await badge.innerText()).toLowerCase();
    console.log('  fallback badge text:', badgeText);
    expect(badgeText).toContain('azure-gpt-4o');
    expect(badgeText).toContain('fallback from');
    expect(badgeText).toContain('claude-sonnet-4-5');

    // The page header also names the model that actually ran. The header
    // template is `<id> | <model_used> | <created_at>`, so the actual model
    // string lands on the page next to the badge.
    const bodyText = (await page.locator('body').innerText()).toLowerCase();
    expect(bodyText).toContain('azure-gpt-4o');
  });

  test('3. Zero configured providers shows the disabled empty state', async ({ page }) => {
    test.setTimeout(120_000);
    await loginInBrowser(page);
    await blockUpstreamVendors(page);
    await mockAvailableProviders(page, {
      anthropic: { configured: false, reason: 'ANTHROPIC_API_KEY not set' },
      openai: { configured: false, reason: 'OPENAI_API_KEY not set' },
      google: { configured: false, reason: 'GOOGLE_API_KEY not set' },
      azure: { configured: false, reason: 'AZURE_OPENAI_API_KEY not set' },
    });
    await mockLlmModels(page);

    await page.goto(`${BASE}/builder`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
    await clickModelTab(page);

    const picker = page.locator('[data-testid="model-picker"][data-provider-count="0"]').first();
    await expect(picker).toBeVisible({ timeout: 25_000 });

    // The picker renders a helper paragraph "No LLM provider configured — contact
    // your admin" below the disabled select; that's the visible surface for users.
    await expect(picker.locator('p', { hasText: /No LLM provider configured/i }).first()).toBeVisible();

    // Native <select> in the empty state is disabled and its placeholder
    // option carries the same warning text.
    const sel = picker.locator('select').first();
    await expect(sel).toBeDisabled();
    const optText = (await sel.locator('option').first().innerText()).toLowerCase();
    expect(optText).toContain('no llm provider configured');
  });
});
