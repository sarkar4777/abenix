import { test, expect } from '@playwright/test';

const API = process.env.API_URL || 'http://localhost:8000';
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || 'admin@abenix.dev';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'Admin123456';

async function loginAdmin(request: any): Promise<string> {
  const r = await request.post(`${API}/api/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  expect(r.status()).toBeLessThan(300);
  const body = await r.json();
  const token = body?.data?.access_token || body?.access_token;
  expect(token, 'admin login token').toBeTruthy();
  return token;
}

test.describe.serial('Model fallback — Claude → Azure GPT-4o', () => {
  let token: string;

  test('1. admin can list models, Azure deployments are surfaced', async ({ request }) => {
    token = await loginAdmin(request);
    const r = await request.get(`${API}/api/llm-models`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(r.status()).toBeLessThan(300);
    const body = await r.json();
    const models: any[] = body?.data?.models || body?.models || [];
    expect(models.length).toBeGreaterThan(5);
    const providers = new Set(models.map((m) => m.provider));
    expect(providers.has('anthropic')).toBeTruthy();
    expect(providers.has('openai')).toBeTruthy();
    expect(providers.has('azure'), 'azure provider must appear in model list').toBeTruthy();
    const azureModels = models.filter((m) => m.provider === 'azure').map((m) => m.value);
    console.log('  azure models surfaced:', azureModels);
    expect(azureModels).toContain('azure-gpt-4o');
  });

  test('2. force claude unavailable via DB flag', async ({ request }) => {
    const r = await request.patch(`${API}/api/admin/llm-pricing/_by-model/claude-sonnet-4-5-20250929`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { fallback_to: ['azure-gpt-4o', 'gpt-4o'] },
    }).catch(() => null);
    const r2 = await request.post(`${API}/api/admin/model-availability/force-status`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { model: 'claude-sonnet-4-5-20250929', status: 'unavailable' },
    });
    expect(r2.status()).toBeLessThan(400);
  });

  test('3. Wingman insight agent run uses azure-gpt-4o, not Claude', async ({ request }) => {
    const WM_API = process.env.WM_API || 'http://localhost:8006';
    const r = await request.post(`${WM_API}/api/agent/run`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { use_case: 'insight', context: { corridor: 'USGC->NWE' } },
      timeout: 180_000,
    });
    expect(r.status()).toBeLessThan(400);
    const j = await r.json();
    const modelUsed = j?.data?.model_used || j?.model_used;
    console.log('  Wingman ran with model:', modelUsed);
    expect(typeof modelUsed).toBe('string');
    expect(modelUsed).not.toMatch(/^claude/i);
  });

  test('4. restore claude availability so the cluster goes back to normal', async ({ request }) => {
    const r = await request.post(`${API}/api/admin/model-availability/force-status`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { model: 'claude-sonnet-4-5-20250929', status: 'available' },
    });
    expect(r.status()).toBeLessThan(400);
  });
});
