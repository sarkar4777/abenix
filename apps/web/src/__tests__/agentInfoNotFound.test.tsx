import { render, screen } from '@testing-library/react';

const state: { error: string | null } = { error: null };

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'a1' }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/agents/a1/info',
  useSearchParams: () => new URLSearchParams(''),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: null, error: state.error, isLoading: false, meta: null, mutate: vi.fn() }),
}));
vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn(async () => ({ data: null, error: null })) }));

import AgentInfoPage from '@/app/(app)/agents/[id]/info/page';

describe('agent Info page for a missing agent', () => {
  it('says the agent is gone instead of spinning forever', () => {
    state.error = 'Agent not found';
    render(<AgentInfoPage />);
    expect(screen.getByTestId('agent-not-found')).toHaveTextContent('This agent is not available');
    expect(screen.getByRole('link', { name: 'Back to agents' })).toHaveAttribute('href', '/agents');
  });

  it('still shows the spinner while the agent loads', () => {
    state.error = null;
    render(<AgentInfoPage />);
    expect(screen.queryByTestId('agent-not-found')).toBeNull();
  });
});
