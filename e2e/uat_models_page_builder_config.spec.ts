import { test, expect, type Page } from '@playwright/test';

/*
 * UAT — Models page exposes the Builder + Pipeline validation model and the
 * Builder UI reflects the saved choice.
 *
 * Steps:
 *   1. Log in as admin (admin@abenix.dev / Admin123456 by default).
 *   2. Open /admin/llm-settings (the Models page).
 *   3. Assert the "Builder + Pipeline validation model" section is visible.
 *   4. Change the dropdown to azure-gpt-4o-mini.
 *   5. Click Save and wait for /api/admin/settings/ai_builder.validation.model PATCH.
 *   6. Navigate to /builder.
 *   7. Assert the BuilderTopBar badge + hidden input reflect azure-gpt-4o-mini.
 *   8. Reset the setting back to azure-gpt-4o so the next UAT phase starts clean.
 *
 * Run:
 *   BASE=http://localhost:3000 API=http://localhost:8000 \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_models_page_builder_config.spec.ts \
 *     --reporter=list --workers=1 --timeout=120000
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

const KEY = 'ai_builder.validation.model';
const DEFAULT_MODEL = 'azure-gpt-4o';
const TARGET_MODEL = 'azure-gpt-4o-mini';

async function login(page: Page): Promise<string> {
  const resp = await page.request.post(`${API}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  expect(resp.ok(), `login failed for ${EMAIL}`).toBeTruthy();
  const body = await resp.json();
  const tok = body?.data?.access_token;
  expect(tok, 'login returned no access_token').toBeTruthy();
  return tok as string;
}

async function seedStorage(page: Page, token: string) {
  await page.goto(BASE);
  await page.evaluate(
    ([t]) => {
      localStorage.setItem('access_token', t);
      localStorage.setItem('token', t);
      // Make sure no stale forced-provider hint leaks in from another spec.
      localStorage.removeItem('ai_builder_force_provider');
    },
    [token],
  );
}

async function setBuilderModelViaApi(
  page: Page,
  token: string,
  value: string,
) {
  const r = await page.request.patch(
    `${API}/api/admin/settings/${encodeURIComponent(KEY)}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      data: { value },
    },
  );
  expect(r.ok(), `PATCH ${KEY} failed: ${r.status()}`).toBeTruthy();
}

test('Models page lets admin pin the Builder + Pipeline validation model', async ({
  page,
}) => {
  test.setTimeout(120_000);

  const token = await login(page);
  await seedStorage(page, token);

  // 1. The new GET endpoint exists and returns a value.
  const getResp = await page.request.get(`${API}/api/settings/builder_model`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(getResp.ok(), '/api/settings/builder_model GET should succeed').toBeTruthy();
  const getBody = await getResp.json();
  expect(getBody?.data?.key).toBe(KEY);
  expect(typeof getBody?.data?.value).toBe('string');

  // 2. Open the Models page (LLM Settings).
  await page.goto(`${BASE}/admin/llm-settings`);
  await page.waitForLoadState('networkidle');

  // 3. The new "Builder + Pipeline validation model" section is visible.
  const section = page.getByTestId('builder-validation-section');
  await expect(section).toBeVisible({ timeout: 15_000 });
  await expect(section).toContainText(/Builder \+ Pipeline validation model/i);

  // 4. The dropdown defaults to azure-gpt-4o (DEFAULTS value).
  const select = page.getByTestId('builder-validation-model-select');
  await expect(select).toBeVisible();

  // 5. Change to azure-gpt-4o-mini.
  await select.selectOption(TARGET_MODEL);
  await expect(select).toHaveValue(TARGET_MODEL);

  // 6. Save.
  await page.getByTestId('save-settings').click();
  // Wait for the PATCH to land, then for the reload.
  await page.waitForResponse(
    (r) =>
      r.url().includes(`/api/admin/settings/${KEY}`) &&
      r.request().method() === 'PATCH' &&
      r.ok(),
    { timeout: 20_000 },
  );

  // 7. Re-read via the public endpoint — the new value must stick.
  const afterResp = await page.request.get(
    `${API}/api/settings/builder_model`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const afterBody = await afterResp.json();
  expect(afterBody?.data?.value).toBe(TARGET_MODEL);

  // 8. Hop to /builder. The badge + hidden input must reflect the new model.
  await page.goto(`${BASE}/builder`);
  await page.waitForLoadState('networkidle');

  const badge = page.getByTestId('builder-validation-model-badge');
  await expect(badge).toBeVisible({ timeout: 15_000 });
  await expect(badge).toContainText(TARGET_MODEL);

  const hidden = page.getByTestId('builder-validation-model-input');
  await expect(hidden).toHaveValue(TARGET_MODEL);

  // 9. Reset to the default so the next phase starts clean.
  await setBuilderModelViaApi(page, token, DEFAULT_MODEL);
  const resetResp = await page.request.get(
    `${API}/api/settings/builder_model`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const resetBody = await resetResp.json();
  expect(resetBody?.data?.value).toBe(DEFAULT_MODEL);
});
