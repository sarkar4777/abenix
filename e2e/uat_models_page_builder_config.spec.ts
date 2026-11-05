import { test, expect, type Page } from '@playwright/test';

/*
 * UAT — Models page exposes the Builder + Pipeline validation model and the
 * Builder UI reflects the saved choice.
 *
 * Steps:
 *   1. Log in as admin (admin@abenix.dev / Admin123456 by default).
 *   2. Open /admin/llm-settings (the Models page).
 *   3. Assert the "Builder + Pipeline validation model" section is visible.
 *   4. Change the picker to another model it offers.
 *   5. Click Save and wait for /api/admin/settings/ai_builder.validation.model PATCH.
 *   6. Navigate to /builder.
 *   7. Assert the BuilderTopBar badge + hidden input reflect the new model.
 *   8. Put the setting back so the next UAT phase starts clean.
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

  const original: string = getBody.data.value;

  // 2. Open the Models page (LLM Settings).
  await page.goto(`${BASE}/admin/llm-settings`, { waitUntil: 'domcontentloaded' });

  // 3. The new "Builder + Pipeline validation model" section is visible.
  const section = page.getByTestId('builder-validation-section');
  await expect(section).toBeVisible({ timeout: 15_000 });
  await expect(section).toContainText(/Builder \+ Pipeline validation model/i);

  // 4. The saved model shows in the picker. Which models it offers depends on the keys this stack has.
  const select = page.getByTestId('builder-validation-model-select').getByTestId('model-picker-select');
  await expect(select).toBeEnabled({ timeout: 15_000 });
  await expect(select).toHaveValue(original);
  const offered = await select.locator('option:not([disabled])').evaluateAll((els) => els.map((e) => (e as HTMLOptionElement).value));
  const target = offered.find((v) => v && v !== original);
  expect(target, 'the picker offers a second model').toBeTruthy();

  // 5. Change it.
  await select.selectOption(target!);
  await expect(select).toHaveValue(target!);

  // 6. Save and wait for the PATCH to land.
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes(`/api/admin/settings/${encodeURIComponent(KEY)}`) &&
        r.request().method() === 'PATCH' &&
        r.ok(),
      { timeout: 20_000 },
    ),
    page.getByTestId('save-settings').click(),
  ]);

  // 7. Re-read via the public endpoint — the new value must stick.
  const afterResp = await page.request.get(
    `${API}/api/settings/builder_model`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const afterBody = await afterResp.json();
  expect(afterBody?.data?.value).toBe(target);

  // 8. Hop to /builder. The badge + hidden input must reflect the new model.
  await page.goto(`${BASE}/builder`, { waitUntil: 'domcontentloaded' });

  // exclusive subscription mode runs the checks on its own model and the badge says so
  const sub = (await (await page.request.get(`${API}/api/admin/settings/subscription`, { headers: { Authorization: `Bearer ${token}` } })).json())?.data;
  const shown = sub?.active && sub?.exclusive ? sub.default_model : target;
  const badge = page.getByTestId('builder-validation-model-badge');
  await expect(badge).toBeVisible({ timeout: 15_000 });
  await expect(badge).toContainText(shown, { timeout: 15_000 });

  const hidden = page.getByTestId('builder-validation-model-input');
  await expect(hidden).toHaveValue(shown);

  // 9. Put back what it was so the next phase starts clean.
  await setBuilderModelViaApi(page, token, original);
  const resetResp = await page.request.get(
    `${API}/api/settings/builder_model`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const resetBody = await resetResp.json();
  expect(resetBody?.data?.value).toBe(original);
});
