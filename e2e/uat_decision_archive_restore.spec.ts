/**
 * An archived decision keeps its key: creating it again says so instead of failing, and restore brings it back.
 *
 *   API=http://localhost:8000 npx playwright test e2e/uat_decision_archive_restore.spec.ts
 */
import { test, expect } from '@playwright/test';

const API = process.env.API || 'http://localhost:8000';
const ADMIN = { email: process.env.AF_EMAIL || 'admin@abenix.dev', password: process.env.AF_PASSWORD || 'Admin123456' };

test('archive, create again, restore', async ({ request }) => {
  const tok = (await (await request.post(`${API}/api/auth/login`, { data: ADMIN })).json()).data.access_token;
  const headers = { Authorization: `Bearer ${tok}` };
  const key = `uat.archive.${Date.now().toString(36)}`;

  expect((await request.post(`${API}/api/decisions`, { headers, data: { key, name: 'Archive me' } })).status()).toBe(201);
  expect((await request.delete(`${API}/api/decisions/${key}`, { headers })).status()).toBe(200);
  expect((await request.get(`${API}/api/decisions/${key}`, { headers })).status()).toBe(404);

  const again = await request.post(`${API}/api/decisions`, { headers, data: { key, name: 'Archive me' } });
  expect(again.status()).toBe(409);
  expect((await again.json()).error.message).toContain('was archived');

  expect((await request.post(`${API}/api/decisions/${key}/restore`, { headers })).status()).toBe(200);
  expect((await request.get(`${API}/api/decisions/${key}`, { headers })).status()).toBe(200);
  expect((await request.post(`${API}/api/decisions/${key}/restore`, { headers })).status()).toBe(409);

  await request.delete(`${API}/api/decisions/${key}`, { headers });
});
