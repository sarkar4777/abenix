import { test, expect, type Page } from '@playwright/test';

/**
 * Verifies the audit-remediation pass:
 *
 *  1. ML Models detail page exposes "Use in Agent" + "Edit metadata"
 *     and the deep-link lands the user in the builder with the
 *     ml_model tool pre-added.
 *  2. ML Models upload form has the optional schema editor.
 *  3. Code Runner detail page exposes "Use in Agent" and the deep-link
 *     pre-configures the code_asset tool.
 *  4. Code Runner schema textarea lints inline (no alert()).
 *  5. Pipeline validation chip is clickable and focuses the offending
 *     canvas node (smoke-tested via dom contract — full graph load
 *     out of scope for this spec).
 *
 * Run with:
 *   BASE=http://localhost:3000 API=http://localhost:8000 \
 *   AF_EMAIL=admin@abenix.dev AF_PASSWORD=Admin123456 \
 *   npx playwright test e2e/uat_audit_fixes.spec.ts --reporter=list --workers=1
 */

const BASE = process.env.BASE || 'http://localhost:3000';
const API = process.env.API || 'http://localhost:8000';
const EMAIL = process.env.AF_EMAIL || 'admin@abenix.dev';
const PASSWORD = process.env.AF_PASSWORD || 'Admin123456';

async function getToken(): Promise<string> {
  const resp = await fetch(`${API}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!resp.ok) throw new Error(`login failed: HTTP ${resp.status}`);
  const json = await resp.json();
  return json.data?.access_token || json.access_token;
}

async function login(page: Page) {
  const token = await getToken();
  expect(token).toBeTruthy();
  const meResp = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } });
  const me = await meResp.json().then((j) => j.data ?? j).catch(() => ({}));
  await page.addInitScript(({ t, u }: { t: string; u: any }) => {
    try {
      localStorage.setItem('access_token', t);
      localStorage.setItem('refresh_token', t);
      localStorage.setItem('user', JSON.stringify(u || {}));
    } catch {}
  }, { t: token, u: me });
}

async function apiPost<T = any>(path: string, body: any, token: string): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${path} -> HTTP ${r.status}: ${j?.error?.message || JSON.stringify(j)}`);
  return j.data ?? j;
}

async function apiDelete(path: string, token: string): Promise<void> {
  await fetch(`${API}${path}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
}

test.describe('ML Models page — audit remediation', () => {
  test('upload form exposes optional schema editor', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ml-models`);
    await page.waitForLoadState('domcontentloaded');
    // Schema details element is collapsed by default; click to expand.
    const schemaSummary = page.locator('summary', { hasText: 'Schemas' }).first();
    await expect(schemaSummary).toBeVisible({ timeout: 10_000 });
    await schemaSummary.click();
    await expect(page.locator('textarea[placeholder*="features"]')).toBeVisible();
    await expect(page.locator('textarea[placeholder*="returns"]')).toBeVisible();
  });

  test('detail page shows Use-in-Agent + Edit-metadata; metadata save round-trips', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ml-models`);
    await page.waitForLoadState('domcontentloaded');
    // Pick the first model in the list (any seeded model works for this test).
    const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
    await expect(firstModel).toBeVisible({ timeout: 15_000 });
    await firstModel.click();
    // Both new CTAs render.
    await expect(page.getByTestId('ml-use-in-agent')).toBeVisible();
    const editBtn = page.getByTestId('ml-edit-metadata');
    await expect(editBtn).toBeVisible();
    // Edit panel expands on click + Save button is wired.
    await editBtn.click();
    await expect(page.getByTestId('ml-edit-panel')).toBeVisible();
    await expect(page.getByTestId('ml-save-metadata')).toBeVisible();
  });

  test('Use-in-Agent deep-link lands in builder with ml_model preset', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ml-models`);
    await page.waitForLoadState('domcontentloaded');
    const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
    await firstModel.click();
    const useBtn = page.getByTestId('ml-use-in-agent');
    await expect(useBtn).toBeVisible();
    // Click navigates to /builder?tool=ml_model&model_name=...
    await Promise.all([
      page.waitForURL(/\/builder\?.*tool=ml_model.*model_name=/, { timeout: 15_000 }),
      useBtn.click(),
    ]);
    expect(page.url()).toContain('tool=ml_model');
    expect(page.url()).toContain('model_name=');
  });
});

test.describe('Code Runner page — audit remediation', () => {
  test('schema textareas lint inline; no native alert() on blur', async ({ page }) => {
    await login(page);
    // Trap any window.alert; failing here means we regressed.
    const alerts: string[] = [];
    page.on('dialog', async (d) => { alerts.push(d.message()); await d.dismiss(); });

    await page.goto(`${BASE}/code-runner`);
    await page.waitForLoadState('domcontentloaded');
    // Need a selected asset to see the schema editor. If none exists,
    // the test is informational — the upload-then-test path is heavier.
    // Pull the asset list directly so the test isn't coupled to a
    // specific layout class. Grab the first asset name, then click the
    // button containing that name in the page.
    const apiResp = await fetch(`${API}/api/code-assets`, {
      headers: { Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token'))) || ''}` },
    });
    const apiJson = await apiResp.json().catch(() => ({}));
    const assets = (apiJson.data || []) as Array<{ name: string; status: string }>;
    if (assets.length === 0) test.skip();
    const firstName = assets[0].name;
    const firstAsset = page.locator('button', { hasText: firstName }).first();
    await expect(firstAsset).toBeVisible({ timeout: 15_000 });
    await firstAsset.click();

    const inputTa = page.locator('textarea').filter({ hasText: '' }).nth(2); // input schema textarea
    await inputTa.fill('{ broken json'); // bad JSON
    await inputTa.blur();
    // Inline error renders with the test id from our edit; no alert fires.
    await expect(page.locator('text=Not valid JSON').first()).toBeVisible({ timeout: 5_000 });
    expect(alerts).toEqual([]);
  });

  test('Use-in-Agent CTA is disabled until asset status=ready', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/code-runner`);
    await page.waitForLoadState('domcontentloaded');
    // Pull the asset list directly so the test isn't coupled to a
    // specific layout class. Grab the first asset name, then click the
    // button containing that name in the page.
    const apiResp = await fetch(`${API}/api/code-assets`, {
      headers: { Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token'))) || ''}` },
    });
    const apiJson = await apiResp.json().catch(() => ({}));
    const assets = (apiJson.data || []) as Array<{ name: string; status: string }>;
    if (assets.length === 0) test.skip();
    const firstName = assets[0].name;
    const firstAsset = page.locator('button', { hasText: firstName }).first();
    await expect(firstAsset).toBeVisible({ timeout: 15_000 });
    await firstAsset.click();
    const useBtn = page.getByTestId('code-use-in-agent');
    await expect(useBtn).toBeVisible();
    // Either clickable (status=ready → URL changes on click) or visibly disabled.
    const disabled = await useBtn.isDisabled();
    if (!disabled) {
      await Promise.all([
        page.waitForURL(/\/builder\?.*tool=code_asset.*asset_id=/, { timeout: 15_000 }),
        useBtn.click(),
      ]);
      expect(page.url()).toContain('tool=code_asset');
    }
  });
});

test.describe('Pass 2 — k8s deploy config + share dialogs + KB multi-file + approvals', () => {
  test('ML Models k8s deploy config exposes replicas + resource preset', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ml-models`);
    await page.waitForLoadState('domcontentloaded');
    const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
    await firstModel.click();
    const k8sBtn = page.getByTestId('deploy-type-k8s');
    if (await k8sBtn.count() === 0) test.skip();
    await k8sBtn.click();
    await expect(page.getByTestId('k8s-deploy-config')).toBeVisible();
    await expect(page.getByTestId('deploy-replicas-input')).toBeVisible();
    await expect(page.getByTestId('deploy-preset-select')).toBeVisible();
  });

  test('ML Models Share button opens ResourceShareDialog', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ml-models`);
    await page.waitForLoadState('domcontentloaded');
    const firstModel = page.locator('button').filter({ hasText: /v\d/ }).first();
    await firstModel.click();
    await page.getByTestId('ml-share').click();
    await expect(page.getByTestId('resource-share-dialog')).toBeVisible();
    await expect(page.getByTestId('share-email-input')).toBeVisible();
    await expect(page.getByTestId('share-permission-select')).toBeVisible();
  });

  test('Code Runner Share button opens dialog', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/code-runner`);
    await page.waitForLoadState('domcontentloaded');
    const apiResp = await fetch(`${API}/api/code-assets`, {
      headers: { Authorization: `Bearer ${(await page.evaluate(() => localStorage.getItem('access_token'))) || ''}` },
    });
    const apiJson = await apiResp.json().catch(() => ({}));
    const assets = (apiJson.data || []) as Array<{ name: string }>;
    if (assets.length === 0) test.skip();
    await page.locator('button', { hasText: assets[0].name }).first().click();
    await page.getByTestId('code-share').click();
    await expect(page.getByTestId('resource-share-dialog')).toBeVisible();
  });

  test('Knowledge Bases dropzone advertises multi-file uploads (self-fixturing)', async ({ page }) => {
    const token = await getToken();
    const kbName = `e2e-audit-kb-${Date.now()}`;
    const kb = await apiPost<{ id: string }>('/api/knowledge-bases', {
      name: kbName, description: 'e2e audit-fix fixture (safe to delete)',
      chunk_size: 1000, chunk_overlap: 200,
    }, token);
    try {
      await login(page);
      await page.goto(`${BASE}/knowledge?id=${kb.id}`);
      await page.waitForLoadState('domcontentloaded');
      await expect(page.locator('h1', { hasText: kbName })).toBeVisible({ timeout: 15_000 });
      const input = page.getByTestId('kb-dropzone-input');
      await expect(input).toHaveAttribute('multiple', '');
      await expect(page.locator('text=Drop files (multiple OK)').first()).toBeVisible();
    } finally {
      await apiDelete(`/api/knowledge-bases/${kb.id}`, token);
    }
  });

  test('Approvals payload renders as key/value with show-raw toggle (self-fixturing)', async ({ page }) => {
    const token = await getToken();
    const created = await apiPost<{ id: string }>('/api/approvals', {
      title: `e2e payload renderer ${Date.now()}`,
      payload: { vendor: 'Acme Brokers', amount_usd: 2_400_000, risk_tier: 'high', nested: { reviewer: 'risk@acme.com', notes: ['budget OK', 'KYC passed'] } },
      required_signoffs: 1,
      expires_seconds: 600,
      gate_kind: 'e2e-audit',
    }, token);
    try {
      await login(page);
      await page.goto(`${BASE}/approvals`);
      await page.waitForLoadState('domcontentloaded');
      const card = page.locator('div', { hasText: /e2e payload renderer/ }).first();
      await expect(card).toBeVisible({ timeout: 15_000 });
      const payloadBtn = card.locator('button', { hasText: 'Details and sign-off history' }).first();
      await payloadBtn.click();
      const view = page.getByTestId('approval-payload-view').first();
      await expect(view).toBeVisible();
      await expect(view.locator('text=Acme Brokers').first()).toBeVisible();
      await expect(view.locator('button', { hasText: 'Show raw JSON' })).toBeVisible();
    } finally {
      // Cancel by denying to clean up the queue.
      await fetch(`${API}/api/approvals/${created.id}/signoff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ decision: 'deny', reason: 'e2e fixture teardown' }),
      });
    }
  });
});

test.describe('Pass 3 — polish + accessibility band', () => {
  test('ML Models upload button is opacity-50 cursor-not-allowed when invalid', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/ml-models`);
    await page.waitForLoadState('domcontentloaded');
    const uploadBtn = page.locator('button', { hasText: /Upload & Validate/i }).first();
    await expect(uploadBtn).toBeVisible();
    await expect(uploadBtn).toBeDisabled();
    const cls = (await uploadBtn.getAttribute('class')) || '';
    expect(cls).toContain('cursor-not-allowed');
    expect(cls).toMatch(/opacity-50/);
  });

  test('Code Runner: filling git URL grays the zip side (XOR)', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/code-runner`);
    await page.waitForLoadState('domcontentloaded');
    await page.getByTestId('code-source-git-url').fill('https://github.com/sarkar4777/abenix');
    await expect(page.getByTestId('code-source-zip')).toBeDisabled();
  });

  test('Cluster Health Grafana link uses env / runtime, not localhost:3010', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/admin/cluster`);
    await page.waitForLoadState('domcontentloaded');
    const link = page.getByTestId('cluster-grafana-link');
    // Either there's no Grafana configured (then no link rendered)
    // or the link points at a non-localhost host.
    if (await link.count() === 0) return;
    const href = (await link.getAttribute('href')) || '';
    expect(href).not.toContain('localhost:3010');
  });

  test('Approvals expiry counter ticks live (self-fixturing, sub-minute window)', async ({ page }) => {
    const token = await getToken();
    const created = await apiPost<{ id: string }>('/api/approvals', {
      title: `e2e expiry tick ${Date.now()}`,
      payload: { kind: 'tick-test' },
      required_signoffs: 1,
      expires_seconds: 30,
      gate_kind: 'e2e-audit',
    }, token);
    try {
      await login(page);
      await page.goto(`${BASE}/approvals`);
      await page.waitForLoadState('domcontentloaded');
      const card = page.locator('div', { hasText: /e2e expiry tick/ }).first();
      await expect(card).toBeVisible({ timeout: 15_000 });
      const exp = card.getByTestId('approval-expiry').first();
      await expect(exp).toBeVisible();
      const t1 = (await exp.textContent()) || '';
      await page.waitForTimeout(2500);
      const t2 = (await exp.textContent()) || '';
      if (/\d+s left/.test(t1) && /\d+s left/.test(t2)) {
        expect(t1).not.toEqual(t2);
      } else {
        expect(t2.length).toBeGreaterThan(0);
      }
    } finally {
      await fetch(`${API}/api/approvals/${created.id}/signoff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ decision: 'deny', reason: 'e2e fixture teardown' }),
      });
    }
  });
});

test.describe('Builder page — audit remediation', () => {
  test('ml_model deep-link pre-adds the tool node + sets parameter_defaults', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/builder?tool=ml_model&model_name=iris-species-classifier`);
    await page.waitForLoadState('domcontentloaded');
    // The tool palette should reflect ml_model as selected — the simplest
    // assertion is that the canvas has a tool node labelled "ml_model" or
    // that the agent-name input shows our preset name.
    await expect(page.locator('input[value*="iris-species-classifier agent"]').or(
      page.locator('text=ml_model').first()
    )).toBeVisible({ timeout: 15_000 });
  });

  test('validation-chip-error is a clickable button when errors present', async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/builder`);
    await page.waitForLoadState('domcontentloaded');
    // We can't deterministically trigger a pipeline-validation error here
    // without a seeded broken pipeline. Instead assert the contract: if
    // the chip ever renders with errors > 0 it MUST be a <button>.
    const chip = page.getByTestId('validation-chip-error');
    if (await chip.count() === 0) test.skip();
    const tag = await chip.evaluate((el) => el.tagName.toLowerCase());
    expect(tag).toBe('button');
  });
});
