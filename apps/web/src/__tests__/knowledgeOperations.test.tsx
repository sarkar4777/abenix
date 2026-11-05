import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api-client', () => ({ apiFetch, API_URL: 'http://test' }));
const role = vi.hoisted(() => ({ value: 'admin' }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: role.value } }) }));
vi.mock('@/stores/toastStore', () => ({ toastSuccess: vi.fn() }));

import { ConnectorsPanel } from '@/components/knowledge/ConnectorsPanel';
import { EmbeddingModelPanel } from '@/components/knowledge/EmbeddingModelPanel';
import { KnowledgeQuotaSection } from '@/components/knowledge/KnowledgeQuotaSection';

afterEach(() => {
  cleanup();
  apiFetch.mockReset();
  role.value = 'admin';
});

const S3 = {
  kind: 's3',
  label: 'S3 compatible object storage',
  needs_admin: false,
  verified_live: true,
  fields: [
    { name: 'bucket', label: 'Bucket', kind: 'text', required: true, help: '', default: null, secret: false },
    { name: 'secret_key', label: 'Secret key', kind: 'secret', required: false, help: '', default: null, secret: true },
  ],
};
const CONFLUENCE = { ...S3, kind: 'confluence', label: 'Confluence', verified_live: false };

function connector(over: object = {}) {
  return {
    id: 'c1',
    name: 'Policies',
    kind: 's3',
    label: S3.label,
    verified_live: true,
    active: true,
    status: 'idle',
    last_error: null,
    cadence_minutes: 60,
    encrypted_at_rest: true,
    last_finished_at: null,
    next_sync_at: null,
    items: { seen: 4, ingested: 2, updated: 0, deleted: 1, failed: 1, skipped: 1 },
    ...over,
  };
}

function route(handlers: Record<string, unknown>) {
  apiFetch.mockImplementation(async (url: string, init?: { method?: string; body?: string }) => {
    const key = `${init?.method ?? 'GET'} ${url}`;
    if (key in handlers) {
      const h = handlers[key];
      return typeof h === 'function' ? (h as (b?: string) => unknown)(init?.body) : h;
    }
    return { data: null };
  });
}

describe('ConnectorsPanel', () => {
  it('says plainly when a kind has only met a simulated service', async () => {
    route({
      'GET /api/knowledge-bases/k/connectors': { data: [] },
      'GET /api/knowledge-connector-kinds': { data: [S3, CONFLUENCE] },
    });
    render(<ConnectorsPanel kbId="k" />);
    await waitFor(() => screen.getByTestId('connectors-empty'));
    fireEvent.click(screen.getByTestId('connector-add'));
    await waitFor(() => screen.getByTestId('connector-kind'));
    fireEvent.change(screen.getByTestId('connector-kind'), { target: { value: 's3' } });
    expect(screen.queryByTestId('connector-unverified')).toBeNull();
    fireEvent.change(screen.getByTestId('connector-kind'), { target: { value: 'confluence' } });
    expect(screen.getByTestId('connector-unverified').textContent).toMatch(/simulated Confluence/);
  });

  it('sends the form and masks secret fields', async () => {
    const created = vi.fn(() => ({ data: connector() }));
    route({
      'GET /api/knowledge-bases/k/connectors': { data: [] },
      'GET /api/knowledge-connector-kinds': { data: [S3] },
      'POST /api/knowledge-bases/k/connectors': created,
    });
    render(<ConnectorsPanel kbId="k" />);
    await waitFor(() => screen.getByTestId('connectors-empty'));
    fireEvent.click(screen.getByTestId('connector-add'));
    await waitFor(() => screen.getByRole('option', { name: S3.label }));
    fireEvent.change(screen.getByTestId('connector-kind'), { target: { value: 's3' } });
    expect((screen.getByTestId('connector-create') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId('connector-name'), { target: { value: 'Policies' } });
    fireEvent.change(screen.getByTestId('connector-field-bucket'), { target: { value: 'docs' } });
    const secret = screen.getByTestId('connector-field-secret_key') as HTMLInputElement;
    expect(secret.type).toBe('password');
    fireEvent.change(secret, { target: { value: 'shh' } });
    fireEvent.click(screen.getByTestId('connector-create'));
    await waitFor(() => expect(created).toHaveBeenCalled());
    const sent = JSON.parse((created.mock.calls[0] as unknown as string[])[0]);
    expect(sent).toMatchObject({ kind: 's3', name: 'Policies', values: { bucket: 'docs', secret_key: 'shh' } });
  });

  it('shows status, the reason items were skipped, and a mass delete waiting on a person', async () => {
    const sync = vi.fn(() => ({ data: {} }));
    route({
      'GET /api/knowledge-bases/k/connectors': {
        data: [connector({ status: 'needs_confirmation', last_error: 'This pass did not find 3 of 4 known items' })],
      },
      'GET /api/knowledge-connector-kinds': { data: [S3] },
      'GET /api/knowledge-bases/k/connectors/c1/items?status=failed&limit=50': { data: [] },
      'GET /api/knowledge-bases/k/connectors/c1/items?status=skipped&limit=50': {
        data: [{ external_id: 'a.zip', name: 'a.zip', status: 'skipped', error: 'Archives are not ingested' }],
      },
      'POST /api/knowledge-bases/k/connectors/c1/sync?confirm_deletes=true': sync,
    });
    render(<ConnectorsPanel kbId="k" />);
    await waitFor(() => screen.getByTestId('connector-row'));
    expect(screen.getByTestId('connector-status').textContent).toMatch(/confirm deletes/);
    expect(screen.getByTestId('connector-last-error').textContent).toMatch(/did not find 3 of 4/);
    fireEvent.click(screen.getByTestId('connector-problems'));
    await waitFor(() => screen.getByTestId('connector-problem-list'));
    expect(screen.getByTestId('connector-problem-list').textContent).toMatch(/Archives are not ingested/);
    fireEvent.click(screen.getByTestId('connector-confirm-deletes'));
    await waitFor(() => expect(sync).toHaveBeenCalled());
  });
});

describe('EmbeddingModelPanel', () => {
  const state = (job: object) => ({
    data: {
      embedding_model: 'text-embedding-3-small',
      supported_models: ['text-embedding-3-small'],
      job: { job_id: 'j', to_model: 'text-embedding-3-large', documents_total: 10, documents_done: 4, chunks: 40, ...job },
    },
  });

  it('offers pause while running and resume with the reason when paused', async () => {
    route({ 'GET /api/knowledge/k/reembed': state({ status: 'paused', error: 'Embedding has cost $5.00 this month' }) });
    render(<EmbeddingModelPanel kbId="k" />);
    await waitFor(() => screen.getByTestId('reembed-paused'));
    expect(screen.getByTestId('reembed-paused').textContent).toMatch(/4 of 10.*Embedding has cost/);
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy();
    cleanup();
    route({ 'GET /api/knowledge/k/reembed': state({ status: 'running' }) });
    render(<EmbeddingModelPanel kbId="k" />);
    await waitFor(() => screen.getByRole('button', { name: 'Pause' }));
    expect(document.body.textContent).toMatch(/4 of 10 documents, 40 chunks/);
  });

  it('calls the control route', async () => {
    const pause = vi.fn(() => ({ data: {} }));
    route({
      'GET /api/knowledge/k/reembed': state({ status: 'running' }),
      'POST /api/knowledge/k/reembed/pause': pause,
    });
    render(<EmbeddingModelPanel kbId="k" />);
    await waitFor(() => screen.getByRole('button', { name: 'Pause' }));
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    await waitFor(() => expect(pause).toHaveBeenCalled());
  });
});

describe('KnowledgeQuotaSection', () => {
  const quota = {
    data: {
      limits: { max_documents: 100, max_chunks: null, max_storage_bytes: 2 * 1024 ** 3, monthly_embedding_usd: null, monthly_cognify_usd: 5 },
      usage: { documents: 12, chunks: 300, storage_bytes: 1024 ** 3, embedding_usd: 1.5, cognify_usd: 0.25 },
    },
  };

  it('saves storage in bytes and blank as no limit', async () => {
    const put = vi.fn(() => ({ data: {} }));
    route({ 'GET /api/knowledge-quotas': quota, 'PUT /api/admin/knowledge-quotas': put });
    render(<KnowledgeQuotaSection />);
    await waitFor(() => screen.getByTestId('knowledge-quota-save'));
    fireEvent.change(screen.getByLabelText('Limit for Storage'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Limit for Documents'), { target: { value: '' } });
    fireEvent.click(screen.getByTestId('knowledge-quota-save'));
    await waitFor(() => expect(put).toHaveBeenCalled());
    const body = JSON.parse((put.mock.calls[0] as unknown as string[])[0]);
    expect(body.max_storage_bytes).toBe(3 * 1024 ** 3);
    expect(body.max_documents).toBeNull();
    expect(body.monthly_cognify_usd).toBe(5);
  });

  it('refuses a bad number and shows members read only usage', async () => {
    route({ 'GET /api/knowledge-quotas': quota });
    render(<KnowledgeQuotaSection />);
    await waitFor(() => screen.getByTestId('knowledge-quota-save'));
    fireEvent.change(screen.getByLabelText('Limit for Documents'), { target: { value: 'many' } });
    expect((screen.getByTestId('knowledge-quota-save') as HTMLButtonElement).disabled).toBe(true);
    cleanup();
    role.value = 'user';
    render(<KnowledgeQuotaSection />);
    await waitFor(() => screen.getByTestId('knowledge-quota-max_documents'));
    expect(screen.queryByTestId('knowledge-quota-save')).toBeNull();
    expect(screen.getByTestId('knowledge-quota-max_documents').textContent).toMatch(/12 of 100/);
    expect(screen.getByTestId('knowledge-quota-max_chunks').textContent).toMatch(/300 of no limit/);
  });
});
