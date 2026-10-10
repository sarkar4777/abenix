import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';

const state: {
  pathname: string;
  perms: any;
  prefs: { sidebar_mode: string } | null;
  counts: any;
  reviews: number;
  marketplace: boolean;
} = { pathname: '/dashboard', perms: null, prefs: null, counts: null, reviews: 0, marketplace: false };

const apiFetch = vi.fn(async (..._args: any[]) => ({ data: { sidebar_mode: 'all' }, error: null }));

vi.mock('next/navigation', () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/hooks/useApi', () => ({
  useApi: (path: string | null) => {
    const data =
      path === '/api/me/permissions' ? state.perms
        : path === '/api/me/ui-prefs' ? state.prefs
          : path === '/api/me/inbox-counts' ? state.counts
            : path === '/api/moderation/reviews/count' ? { pending: state.reviews }
              : null;
    return { data, error: null, isLoading: false, meta: null, mutate: vi.fn() };
  },
}));
vi.mock('@/hooks/usePlatformFeatures', () => ({
  usePlatformFeatures: () => ({ marketplace: state.marketplace, monetization: false, loaded: true }),
}));
vi.mock('@/lib/api-client', () => ({ apiFetch: (...a: any[]) => apiFetch(...a) }));

import { NAV_ROUTE_LABELS, SidebarNav } from '@/components/layout/Sidebar';
import { SIDEBAR_MODE_KEY } from '@/lib/inbox';

const MEMBER_FEATURES = {
  view_dashboard: true, create_agents: true, use_builder: true, create_pipelines: true, use_chat: true,
  use_kb: true, use_persona: true, use_ml_models: true, use_code_runner: true, use_meetings: true,
  use_triggers: true, view_executions: true, view_analytics: true, view_alerts: true, use_marketplace: true,
  use_sdk_playground: true, use_load_playground: true, review_queue: false, manage_team: false,
  manage_settings: false, manage_api_keys: true, manage_mcp: true, publish_to_marketplace: false,
};
const USER_CAPS = ['decisions.view', 'decisions.evaluate', 'risk.view', 'evals.run', 'runs.replay', 'autonomy.view', 'actions.review'];

function as(role: 'user' | 'creator' | 'admin', caps: string[] = USER_CAPS) {
  const admin = role === 'admin';
  state.perms = {
    role,
    is_admin: admin,
    features: { ...MEMBER_FEATURES, ...(admin ? { review_queue: true, manage_team: true, manage_settings: true, publish_to_marketplace: true } : {}) },
    capabilities: admin ? ['*'] : caps,
  };
  return role;
}

function nav(role: string) {
  return render(<SidebarNav collapsed={false} pathname={state.pathname} userRole={role} />);
}

const labels = () => screen.getAllByRole('link').map((a) => a.textContent?.trim());

beforeEach(() => {
  state.pathname = '/dashboard';
  state.prefs = null;
  state.counts = null;
  state.reviews = 0;
  state.marketplace = false;
  localStorage.clear();
  apiFetch.mockClear();
});

describe('sidebar essentials mode', () => {
  it('is the default and shows the short list for a member', () => {
    nav(as('user'));
    expect(screen.getByTestId('sidebar-essentials')).toBeInTheDocument();
    expect(labels()).toEqual(['Needs you', 'Home', 'Agents', 'AI Chat', 'Knowledge', 'Monitor']);
    expect(screen.queryByTestId('sidebar-admin-toggle')).toBeNull();
  });

  it('adds Agent Builder, Decisions, Approvals and Autonomy for creators', () => {
    nav(as('creator'));
    expect(labels()).toEqual(['Needs you', 'Home', 'Agents', 'AI Chat', 'Knowledge', 'Monitor', 'Agent Builder', 'Decisions', 'Approvals', 'Autonomy']);
  });

  it('adds Approvals for a member who can approve decisions', () => {
    nav(as('user'));
    state.perms.can_approve_decisions = true;
    cleanup();
    nav('user');
    expect(labels()).toEqual(['Needs you', 'Home', 'Agents', 'AI Chat', 'Knowledge', 'Monitor', 'Approvals']);
  });

  it('adds Improvements for builders who can view it, never for members', () => {
    nav(as('creator', [...USER_CAPS, 'improvements.view']));
    expect(labels()).toEqual(['Needs you', 'Home', 'Agents', 'AI Chat', 'Knowledge', 'Monitor', 'Agent Builder', 'Decisions', 'Approvals', 'Autonomy', 'Improvements']);
    cleanup();
    nav(as('user', [...USER_CAPS, 'improvements.view']));
    expect(labels()).not.toContain('Improvements');
  });

  it('adds an Admin section for admins that opens to the admin pages', () => {
    nav(as('admin'));
    expect(labels()).toContain('Agent Builder');
    expect(screen.queryByText('Cluster Health')).toBeNull();
    fireEvent.click(screen.getByTestId('sidebar-admin-toggle'));
    const admin = screen.getByTestId('sidebar-admin-items');
    expect(within(admin).getByText('Cluster Health')).toBeInTheDocument();
    expect(within(admin).getByText('Permissions')).toBeInTheDocument();
  });

  it('shows the live Needs you total', () => {
    state.counts = { total: 7, counts: { approvals: 7 }, available: ['approvals'] };
    nav(as('user'));
    expect(screen.getByTestId('sidebar-inbox-count')).toHaveTextContent('7');
  });

  it('says what the Needs you total is made of', () => {
    state.counts = { total: 121, counts: { approvals: 1, watching: 120 }, available: ['approvals', 'watching'] };
    nav(as('user'));
    expect(screen.getByTestId('sidebar-inbox-count')).toHaveAttribute('title', 'Waiting on you: 1 to sign, 120 watching reviews');
  });

  it('caps the badge at 99+', () => {
    state.counts = { total: 120, counts: {}, available: [] };
    nav(as('user'));
    expect(screen.getByTestId('sidebar-inbox-count')).toHaveTextContent('99+');
  });

  it('keeps the current page visible when it is not an essential', () => {
    state.pathname = '/tools';
    nav(as('user'));
    expect(within(screen.getByTestId('sidebar-current-page')).getByText('Tools Catalogue')).toBeInTheDocument();
  });

  it('adds the Review inbox and its count for a member who reviews held content', () => {
    state.reviews = 2;
    nav(as('user', [...USER_CAPS, 'moderation.review']));
    expect(labels()).toEqual(['Needs you', 'Review inbox2', 'Home', 'Agents', 'AI Chat', 'Knowledge', 'Monitor']);
    expect(screen.getByTestId('sidebar-review-count')).toHaveTextContent('2');
  });

  it('still respects capability gates', () => {
    nav(as('creator', USER_CAPS.filter((c) => c !== 'autonomy.view')));
    expect(labels()).not.toContain('Autonomy');
  });
});

describe('sidebar all mode', () => {
  it('toggles to the full grouped list and saves the choice on the server', () => {
    state.reviews = 3;
    nav(as('admin'));
    fireEvent.click(screen.getByTestId('sidebar-mode-toggle'));
    expect(screen.getByTestId('sidebar-all')).toBeInTheDocument();
    expect(screen.getByText('Tools Catalogue')).toBeInTheDocument();
    expect(screen.getByText('Review inbox')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-review-count')).toHaveTextContent('3');
    expect(apiFetch).toHaveBeenCalledWith('/api/me/ui-prefs', expect.objectContaining({ method: 'PUT', body: JSON.stringify({ sidebar_mode: 'all' }) }));
    expect(localStorage.getItem(SIDEBAR_MODE_KEY)).toBe('all');
    expect(screen.getByTestId('sidebar-mode-toggle')).toHaveTextContent('Show essentials only');
  });

  it('keeps every sidebar route for an admin', () => {
    state.prefs = { sidebar_mode: 'all' };
    state.marketplace = true;
    nav(as('admin'));
    const hrefs = new Set(Array.from(document.querySelectorAll('[data-nav]')).map((a) => a.getAttribute('data-nav')));
    for (const href of Object.keys(NAV_ROUTE_LABELS)) expect(hrefs.has(href)).toBe(true);
    expect(hrefs.has('/inbox')).toBe(true);
  });

  it('uses the server choice over the local cache', () => {
    localStorage.setItem(SIDEBAR_MODE_KEY, 'essentials');
    state.prefs = { sidebar_mode: 'all' };
    nav(as('user'));
    expect(screen.getByTestId('sidebar-all')).toBeInTheDocument();
  });

  it('paints from the local cache before the server answers', () => {
    localStorage.setItem(SIDEBAR_MODE_KEY, 'all');
    nav(as('user'));
    expect(screen.getByTestId('sidebar-all')).toBeInTheDocument();
  });

  it('keeps the gates in all mode', () => {
    state.prefs = { sidebar_mode: 'all' };
    nav(as('user', []));
    expect(screen.queryByText('Decisions')).toBeNull();
    expect(screen.queryByText('Cluster Health')).toBeNull();
    expect(screen.queryByText('Review inbox')).toBeNull();
    expect(screen.getByText('Needs you')).toBeInTheDocument();
  });

  it('survives blocked storage', () => {
    const get = vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    nav(as('user'));
    expect(screen.getByTestId('sidebar-essentials')).toBeInTheDocument();
    get.mockRestore();
  });
});
