import { render, screen, waitFor } from '@testing-library/react';

const seen: string[] = [];

vi.mock('next/navigation', () => ({
  usePathname: () => '/agents',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => {
    if (path) seen.push(path);
    return { data: path?.startsWith('/api/agents?') ? [] : null, isLoading: false, error: null, meta: { total: 0 }, mutate: vi.fn() };
  },
}));
vi.mock('@/hooks/usePlatformFeatures', () => ({
  usePlatformFeatures: () => ({ marketplace: false, monetization: false, loaded: true }),
}));
vi.mock('@/lib/fetch-all-agents', () => ({
  fetchAllAgents: () => Promise.resolve({ agents: [{ id: '1', agent_type: 'oob' }, { id: '2', agent_type: 'oob' }], total: 2 }),
}));

import AgentsPage from '@/app/(app)/agents/page';

describe('agents page first view', () => {
  it('opens on every agent the person can use, not their own empty list', async () => {
    window.history.replaceState({}, '', '/agents');
    render(<AgentsPage />);
    expect(screen.getByTestId('agents-tab-all')).toHaveAttribute('aria-pressed', 'true');
    expect(seen.find((p) => p.startsWith('/api/agents?'))).not.toContain('scope=mine');
    await waitFor(() => expect(screen.getByText('2 agents available')).toBeInTheDocument());
  });
});
