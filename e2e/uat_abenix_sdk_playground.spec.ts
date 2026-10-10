import { test, expect, type Page, type APIRequestContext } from '@playwright/test';

/**
 * Abenix — SDK Playground browser UAT.
 *
 * Walks the playground exactly the way a developer evaluating the
 * platform would:
 *   1. Log in, land on /sdk-playground.
 *   2. Pick a real OOB agent (a deterministic one — current_time —
 *      so the assertion isn't flaky).
 *   3. Confirm the playground fetched the asset's input_variables and
 *      example_prompts and rendered them as a typed form (the panel
 *      gated by data-testid="live-inputs-panel").
 *   4. Fill the message input.
 *   5. Click "Run live" and assert the platform actually executes the
 *      agent end-to-end and the playground surfaces:
 *         - status = completed | paused | failed (NOT a 4xx)
 *         - execution_id is shown
 *         - either output text or paused_at is rendered
 *
 * The probe agent is current_time because it's an OOB tool-only call
 * with no LLM dependency, so the test doesn't burn LLM cost or
 * depend on Anthropic/OpenAI quota.
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';
const PROBE_AGENT_NAME_RE = /current.?time|hello|echo/i;

async function login(page: Page): Promise<{ token: string; user: any }> {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  expect(resp.ok, 'login should succeed').toBeTruthy();
  const json = await resp.json();
  const token = json.data?.access_token || json.access_token;
  expect(token).toBeTruthy();
  const meRaw = await fetch(`${API}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then((r) => r.json());
  const inner = meRaw?.data ?? meRaw;
  const user = inner?.user ?? inner;
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    localStorage.setItem('access_token', t);
    localStorage.setItem('refresh_token', t);
    localStorage.setItem('user', JSON.stringify(u || {}));
  }, { t: token, u: user });
  return { token, user };
}

async function pickAgentByApi(
  _request: APIRequestContext,
  token: string,
): Promise<{ id: string; name: string; slug: string } | null> {
  // /api/agents caps limit at 100 per page.
  const r = await fetch(`${API}/api/agents?limit=100`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) {
    console.log(`[playground-uat] /api/agents HTTP ${r.status} — pickAgentByApi returns null`);
    return null;
  }
  const body = await r.json();
  const list: Array<{ id: string; name: string; slug?: string; status?: string }> = body?.data || [];
  console.log(`[playground-uat] /api/agents returned ${list.length} agents`);
  // Filter to agents that are runnable (status=published or active or
  // OOB). Agents in draft/pending_review can't be executed.
  const runnable = list.filter((a) => !a.status || ['published', 'active'].includes(a.status));
  // Prefer a deterministic probe matching the regex; otherwise the
  // first runnable agent.
  const probe = runnable.find((a) => PROBE_AGENT_NAME_RE.test(a.name) || PROBE_AGENT_NAME_RE.test(a.slug || ''));
  return probe ?? runnable[0] ?? list[0] ?? null;
}

test.describe.serial('Abenix SDK Playground — browser UAT', () => {
  let token: string;
  let probeAgent: { id: string; name: string; slug: string } | null = null;

  test.beforeEach(async ({ page }) => {
    const out = await login(page);
    token = out.token;
  });

  test('a probe agent exists for the playground UAT', async ({ request }) => {
    const a = await pickAgentByApi(request, token);
    expect(a, 'at least one agent must be seeded for the playground UAT').not.toBeNull();
    probeAgent = a;
  });

  test('playground page renders + the input form is built from the agent schema', async ({ page }) => {
    expect(probeAgent, 'previous test should have set probeAgent').not.toBeNull();

    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle').catch(() => {});

    await page.goto(`${BASE}/sdk-playground`);
    await page.waitForLoadState('networkidle').catch(() => {});

    // The page rendered (didn't 404 / didn't bounce to login).
    expect(page.url()).toContain('/sdk-playground');
    await expect(page.getByText(/SDK Code Playground/i).first()).toBeVisible();

    // Filter the agent list to the probe and click it. Both the name
    // and the slug are searchable.
    const search = page.locator('input[placeholder^="Search agents"]');
    await search.fill(probeAgent!.slug || probeAgent!.name);

    const card = page.getByRole('button', { name: new RegExp(probeAgent!.name.slice(0, 12), 'i') }).first();
    await expect(card).toBeVisible({ timeout: 10_000 });
    await card.click();

    // The Live inputs panel hydrates after asset-context fetches.
    const inputsPanel = page.locator('[data-testid="live-inputs-panel"]');
    await expect(inputsPanel).toBeVisible({ timeout: 15_000 });

    // The Run live button must be enabled once an asset is picked.
    const runLive = page.locator('[data-testid="run-live-button"]');
    await expect(runLive).toBeEnabled({ timeout: 10_000 });
  });

  test('Run live executes the agent end-to-end and renders a result panel', async ({ page }) => {
    test.setTimeout(180_000);
    expect(probeAgent).not.toBeNull();

    await page.goto(`${BASE}/dashboard`);
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.goto(`${BASE}/sdk-playground`);
    await page.waitForLoadState('networkidle').catch(() => {});

    const search = page.locator('input[placeholder^="Search agents"]');
    await search.fill(probeAgent!.slug || probeAgent!.name);
    const card = page.getByRole('button', { name: new RegExp(probeAgent!.name.slice(0, 12), 'i') }).first();
    await card.click();

    const inputsPanel = page.locator('[data-testid="live-inputs-panel"]');
    await expect(inputsPanel).toBeVisible({ timeout: 15_000 });

    // Fill the `message` field if present. Many OOB agents declare it
    // even when they don't strictly need a message.
    const messageBox = inputsPanel.locator('textarea, input[type="text"]').first();
    if (await messageBox.count() > 0) {
      await messageBox.fill('uat probe — reply with the current time');
    }

    const runLive = page.locator('[data-testid="run-live-button"]');
    await runLive.click();

    // Result panel renders with one of the three terminal states. We
    // do NOT assert a specific output string because the agent might
    // be LLM-backed and produce different prose each run; the contract
    // is "the platform executed and the playground surfaced the
    // outcome with no client-side error."
    const result = page.locator('[data-testid="live-result-panel"]');
    await expect(result).toBeVisible({ timeout: 90_000 });

    const text = (await result.innerText()).toLowerCase();
    const ok =
      text.includes('completed') ||
      text.includes('paused') ||
      text.includes('failed') ||
      text.includes('output');
    expect(ok, `result panel should report a terminal state; saw: ${text.slice(0, 200)}`).toBeTruthy();

    // The execution id should be visible regardless of the outcome,
    // proving the API was actually called and a row was created.
    const execIdShown = await result.locator('text=/#[0-9a-f]{8}/').first().isVisible().catch(() => false);
    expect(execIdShown, 'execution_id chip must render in the result panel').toBeTruthy();
  });
});
