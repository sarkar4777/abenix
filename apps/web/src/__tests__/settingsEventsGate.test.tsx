import { render, screen } from '@testing-library/react';

const permsState: { perms: { capabilities: string[] } | undefined; loading: boolean } = {
  perms: undefined,
  loading: false,
};

vi.mock('next/navigation', () => ({
  usePathname: () => '/settings/profile',
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => permsState };
});
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: undefined, isLoading: false, mutate: vi.fn() }),
}));
vi.mock('@/lib/fetch-all-agents', () => ({
  fetchAllAgents: () => Promise.resolve({ agents: [] }),
}));

import SettingsLayout from '@/app/(app)/settings/layout';
import EventsSettingsPage from '@/app/(app)/settings/webhooks/page';

describe('settings Events entry', () => {
  it('is hidden without events.manage', () => {
    permsState.perms = { capabilities: ['agents.view'] };
    render(<SettingsLayout>body</SettingsLayout>);
    expect(screen.queryByRole('link', { name: /Events/ })).toBeNull();
    expect(screen.getByRole('link', { name: /Profile/ })).toBeInTheDocument();
  });

  it('shows for a holder of events.manage', () => {
    permsState.perms = { capabilities: ['events.manage'] };
    render(<SettingsLayout>body</SettingsLayout>);
    expect(screen.getByRole('link', { name: /Events/ })).toHaveAttribute('href', '/settings/webhooks');
  });
});

describe('Events page', () => {
  it('explains the missing capability', () => {
    permsState.perms = { capabilities: [] };
    render(<EventsSettingsPage />);
    expect(screen.getByTestId('events-no-access')).toHaveTextContent('events.manage');
    expect(screen.queryByTestId('sub-new')).toBeNull();
  });

  it('lets a manager create subscriptions', () => {
    permsState.perms = { capabilities: ['events.manage'] };
    render(<EventsSettingsPage />);
    expect(screen.getByTestId('sub-new')).toBeInTheDocument();
    expect(screen.getByTestId('sub-empty')).toBeInTheDocument();
  });
});
