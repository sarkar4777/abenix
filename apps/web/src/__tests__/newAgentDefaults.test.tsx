import { render, screen, waitFor } from '@testing-library/react';
import { ModelPicker } from '@/components/ModelPicker';
import { sortForPicker } from '@/lib/fetch-all-agents';
import { fetchDefaultModel } from '@/lib/models';

describe('sortForPicker', () => {
  it('lists the caller drafts first, newest first, then the rest by name', () => {
    const rows = [
      { name: 'Zeta', status: 'active', updated_at: '2026-10-09T10:00:00Z' },
      { name: 'Alpha', status: 'active', updated_at: '2026-01-01T00:00:00Z' },
      { name: 'Old draft', status: 'draft', updated_at: '2026-01-01T00:00:00Z' },
      { name: 'Zz new draft', status: 'draft', updated_at: '2026-10-09T09:00:00Z' },
    ];
    expect(sortForPicker(rows).map((r) => r.name)).toEqual(['Zz new draft', 'Old draft', 'Alpha', 'Zeta']);
  });
});

function mockApi(models: unknown[], providers: Record<string, unknown>, subscription: unknown) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const data = url.includes('available-providers') ? providers : { models, subscription };
    return { ok: true, json: async () => ({ data }) };
  }));
}

const subOnly = {
  anthropic: { configured: false },
  openai: { configured: false },
  claude_subscription: { configured: true },
};

describe('ModelPicker on a subscription-only install', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('offers the subscription-served models instead of an empty list', async () => {
    mockApi(
      [
        { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5', provider: 'anthropic', subscription_served: true },
        { value: 'claude-opus-5', label: 'Claude Opus 5', provider: 'anthropic', subscription_served: true },
        { value: 'gpt-4o', label: 'GPT-4o', provider: 'openai', subscription_served: false },
      ],
      subOnly,
      { enabled: true, token_set: true, active: true, exclusive: false, default_model: 'claude-haiku-4-5' },
    );
    render(<ModelPicker value="claude-haiku-4-5" onChange={() => {}} />);
    const select = await screen.findByTestId('model-picker-select');
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('claude-haiku-4-5'));
    const values = Array.from((select as HTMLSelectElement).options).map((o) => o.value);
    expect(values).toContain('claude-opus-5');
    expect(values).not.toContain('gpt-4o');
  });

  it('shows a saved model it cannot offer rather than the first option', async () => {
    mockApi(
      [{ value: 'claude-opus-5', label: 'Claude Opus 5', provider: 'anthropic', subscription_served: true }],
      subOnly,
      null,
    );
    render(<ModelPicker value="gpt-4o" onChange={() => {}} />);
    const select = (await screen.findByTestId('model-picker-select')) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe('gpt-4o'));
    expect(select.selectedOptions[0].textContent).toContain('not available');
  });
});

describe('fetchDefaultModel', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('returns the default the API picked for new agents', async () => {
    mockApi(
      [{ value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5', provider: 'anthropic' }],
      {},
      null,
    );
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementationOnce(async () => ({
      ok: true,
      json: async () => ({ data: { models: [{ value: 'claude-haiku-4-5' }], subscription: null, default_model: 'claude-haiku-4-5' } }),
    }));
    expect(await fetchDefaultModel()).toBe('claude-haiku-4-5');
  });
});
