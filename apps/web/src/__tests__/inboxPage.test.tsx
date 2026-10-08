import { render, screen } from '@testing-library/react';

const state: { counts: any; tab: string | null; role: string; caps: string[] } = { counts: null, tab: null, role: 'user', caps: [] };
const replace = vi.fn();

vi.mock('next/navigation', () => ({
  usePathname: () => '/inbox',
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(state.tab ? `tab=${state.tab}` : ''),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => ({
    data: path === '/api/me/inbox-counts' ? state.counts : null,
    error: null,
    isLoading: false,
    meta: null,
    mutate: vi.fn(),
  }),
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'u1', role: state.role } }) }));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => ({ perms: { capabilities: state.caps, is_admin: state.role === 'admin' }, loading: false }) };
});
vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn(async () => ({ data: null, error: null })) }));
vi.mock('@/components/inbox/ApprovalsPanel', () => ({ default: () => <div data-testid="stub-approvals" /> }));
vi.mock('@/components/inbox/AlertsPanel', () => ({ default: () => <div data-testid="stub-alerts" /> }));
vi.mock('@/components/autonomy/ReviewQueue', () => ({ default: () => <div data-testid="stub-watching" /> }));
vi.mock('@/components/moderation/HeldInbox', () => ({ default: () => <div data-testid="stub-held" /> }));
vi.mock('@/app/(app)/review-queue/MarketplaceSubmissions', () => ({ default: () => <div data-testid="stub-marketplace" /> }));

import InboxPage from '@/app/(app)/inbox/page';
import { canSign } from '@/lib/inbox';

beforeEach(() => {
  state.counts = null;
  state.tab = null;
  state.role = 'user';
  state.caps = [];
  localStorage.clear();
});

describe('Needs you page', () => {
  it('says nothing needs you and lists what will show up', () => {
    state.counts = { total: 0, counts: { approvals: 0, watching: 0, alerts: 0 }, available: ['approvals', 'watching', 'alerts'] };
    render(<InboxPage />);
    expect(screen.getByTestId('inbox-empty')).toHaveTextContent('Nothing needs you right now');
    expect(screen.getByTestId('inbox-empty')).toHaveTextContent('Watching reviews');
    expect(screen.getByTestId('page-purpose')).toBeInTheDocument();
    expect(screen.getByTestId('page-primary-action')).toHaveTextContent('Go to Home');
  });

  it('opens the busiest tab with counts on every tab', () => {
    state.counts = { total: 5, counts: { approvals: 0, watching: 2, alerts: 3 }, available: ['approvals', 'watching', 'alerts'] };
    state.caps = ['actions.review'];
    render(<InboxPage />);
    expect(screen.getByTestId('inbox-tab-watching')).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByTestId('inbox-count-watching')).toHaveTextContent('2');
    expect(screen.getByTestId('inbox-count-alerts')).toHaveTextContent('3');
    expect(screen.getByTestId('stub-watching')).toBeInTheDocument();
    expect(screen.getByTestId('inbox-open-full')).toHaveAttribute('href', '/approvals?tab=reviews');
  });

  it('explains a tab the person cannot use', () => {
    state.counts = { total: 1, counts: { approvals: 1 }, available: ['approvals'] };
    state.tab = 'held';
    render(<InboxPage />);
    expect(screen.getByTestId('inbox-not-for-you')).toHaveTextContent('Review held content permission');
    expect(screen.queryByTestId('stub-held')).toBeNull();
  });

  it('shows the marketplace tab only when the server offers it', () => {
    state.role = 'admin';
    state.counts = { total: 4, counts: { approvals: 1, held: 0, marketplace: 3 }, available: ['approvals', 'held', 'marketplace'] };
    state.tab = 'marketplace';
    render(<InboxPage />);
    expect(screen.getByTestId('stub-marketplace')).toBeInTheDocument();
    expect(screen.queryByTestId('inbox-tab-alerts')).toBeNull();
  });
});

describe('canSign', () => {
  const me = { id: 'u1', role: 'creator' };
  it('follows the same rules as the server', () => {
    expect(canSign({ id: 'a' }, me, [])).toBe(true);
    expect(canSign({ id: 'a' }, { id: 'u1', role: 'user' }, [])).toBe(false);
    expect(canSign({ id: 'a' }, { id: 'u1', role: 'user' }, ['approvals.sign'])).toBe(true);
    expect(canSign({ id: 'a', signoffs: [{ user_id: 'u1' }] }, me, [])).toBe(false);
    expect(canSign({ id: 'a', gate_kind: 'decision_publish' }, me, [])).toBe(false);
    expect(canSign({ id: 'a', gate_kind: 'autonomy.promote', payload: { agent_creator_id: 'u1' } }, me, [])).toBe(false);
    expect(canSign({ id: 'a', policy: { capability: 'approvals.sign:legal' } }, me, ['approvals.sign'])).toBe(true);
    expect(canSign({ id: 'a', policy: { exclude_requester: true }, requested_by: 'u1' }, me, ['approvals.sign'])).toBe(false);
    expect(canSign({ id: 'hitl:e:g' }, me, [])).toBe(true);
  });
});
