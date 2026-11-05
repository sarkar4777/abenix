import { render, screen } from '@testing-library/react';

const state: { capabilities: string[] } = { capabilities: [] };

vi.mock('next/navigation', () => ({
  usePathname: () => '/decisions',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(''),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: [], isLoading: false, error: null, meta: null, mutate: vi.fn() }),
}));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => ({ perms: { capabilities: state.capabilities }, loading: false }) };
});

import DecisionsPage from '@/app/(app)/decisions/page';

describe('reference sets link on Decisions', () => {
  it('is there for an author, next to New decision', () => {
    state.capabilities = ['decisions.view', 'decisions.author'];
    render(<DecisionsPage />);
    expect(screen.getByRole('link', { name: /Reference sets/ })).toHaveAttribute('href', '/decisions/reference-sets');
    expect(screen.getByTestId('decision-new')).toBeInTheDocument();
  });

  it('is still there for someone who only reads', () => {
    state.capabilities = ['decisions.view'];
    render(<DecisionsPage />);
    expect(screen.getByRole('link', { name: /Reference sets/ })).toHaveAttribute('href', '/decisions/reference-sets');
    expect(screen.queryByTestId('decision-new')).toBeNull();
  });
});
