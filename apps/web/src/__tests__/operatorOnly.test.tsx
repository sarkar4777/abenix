import { render, screen, waitFor } from '@testing-library/react';

const state: { features: { can_change: boolean; operator_rule: string } | null } = {
  features: { can_change: false, operator_rule: 'Admins of the platform tenant, the one that holds the system account.' },
};
const pricing = { rows: [{ id: 'r1', model: 'gpt-5', provider: 'openai', input_per_m: 1, output_per_m: 2 }], providers: ['openai'] };
const settings = { categories: { general: [{ key: 'k1', value: 'm', default: 'm', is_default: true, kind: 'string', description: 'd' }] } };
const apiFetch = vi.fn(async (path: string) => ({
  data: path.includes('llm-pricing') ? pricing : path.includes('/settings/subscription') ? null : path.includes('/admin/settings') ? settings : null,
  error: null,
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/admin',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/lib/api-client', () => ({ apiFetch: (p: string) => apiFetch(p), API_URL: '' }));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  const perms = { role: 'admin', is_admin: true, features: { manage_settings: true }, capabilities: ['*'] };
  return { ...actual, useMyPermissions: () => ({ perms, loading: false, failed: false, retry: vi.fn() }) };
});
const pending = [{ id: 'a1', name: 'Waiting', status: 'pending_review', model_config: { tools: [] }, created_at: '2026-01-01T00:00:00Z' }];
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => ({
    data: path === '/api/admin/platform-features' ? state.features : path?.includes('pending_review') ? pending : null,
    error: null,
    isLoading: false,
    meta: null,
    mutate: vi.fn(),
  }),
}));

import ClusterPage from '@/app/(app)/admin/cluster/page';
import LlmPricingPage from '@/app/(app)/admin/llm-pricing/page';
import LlmSettingsPage from '@/app/(app)/admin/llm-settings/page';
import ToolScalingPage from '@/app/(app)/admin/tool-scaling/page';
import MarketplaceSubmissions from '@/app/(app)/review-queue/MarketplaceSubmissions';

const asTenantAdmin = () => {
  state.features = { can_change: false, operator_rule: 'Admins of the platform tenant, the one that holds the system account.' };
};
const asOperator = () => {
  state.features = { can_change: true, operator_rule: 'x' };
};

beforeEach(() => {
  apiFetch.mockClear();
  localStorage.setItem('access_token', 't');
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ data: [{ slug: 'web_search' }] }) } as Response)) as unknown as typeof fetch;
});

describe('actions only a platform operator can take', () => {
  it('explains Cluster Health to a tenant admin and never asks for it', async () => {
    asTenantAdmin();
    render(<ClusterPage />);
    expect(screen.getByTestId('no-access-who')).toHaveTextContent('only a platform operator can use it');
    expect(screen.getByTestId('no-access-who')).toHaveTextContent('Admins of the platform tenant');
    expect(apiFetch).not.toHaveBeenCalledWith('/api/admin/cluster/overview');
  });

  it('opens Cluster Health for an operator', async () => {
    asOperator();
    render(<ClusterPage />);
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith('/api/admin/cluster/overview'));
    expect(screen.queryByTestId('no-access-who')).toBeNull();
  });

  it('shows pricing read only to a tenant admin', async () => {
    asTenantAdmin();
    render(<LlmPricingPage />);
    await screen.findByTestId('row-gpt-5');
    expect(screen.getByTestId('operator-only-note')).toHaveTextContent('only a platform operator can change it');
    expect(screen.queryByTestId('add-pricing-row')).toBeNull();
    expect(screen.queryByLabelText('Delete pricing for gpt-5')).toBeNull();
    expect(screen.getByLabelText('Input price for gpt-5')).toBeDisabled();
  });

  it('keeps pricing editable for an operator', async () => {
    asOperator();
    render(<LlmPricingPage />);
    await screen.findByTestId('row-gpt-5');
    expect(screen.queryByTestId('operator-only-note')).toBeNull();
    expect(screen.getByTestId('add-pricing-row')).toBeInTheDocument();
    expect(screen.getByLabelText('Input price for gpt-5')).toBeEnabled();
  });

  it('removes save and reset from Model Selection for a tenant admin', async () => {
    asTenantAdmin();
    render(<LlmSettingsPage />);
    await screen.findByTestId('operator-only-note');
    expect(screen.queryByTestId('save-settings')).toBeNull();
    expect(screen.queryByTestId('reset-settings')).toBeNull();
  });

  it('removes Edit from tool scaling for a tenant admin', async () => {
    asTenantAdmin();
    render(<ToolScalingPage />);
    await screen.findByTestId('operator-only-note');
    expect(screen.queryByRole('button', { name: 'Edit web_search' })).toBeNull();
  });

  it('removes Approve and Reject from the marketplace queue for a tenant admin', () => {
    asTenantAdmin();
    render(<MarketplaceSubmissions />);
    expect(screen.getByText('Waiting')).toBeInTheDocument();
    expect(screen.getByTestId('operator-only-note')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
  });

  it('keeps Approve and Reject for an operator', () => {
    asOperator();
    render(<MarketplaceSubmissions />);
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
  });
});
