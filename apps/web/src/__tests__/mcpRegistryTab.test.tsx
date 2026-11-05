import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
const noConnections: unknown[] = [];
vi.mock('@/hooks/useApi', () => ({
  useApi: () => ({ data: noConnections, isLoading: false, error: null, meta: null, mutate: vi.fn() }),
}));
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));
vi.mock('@/hooks/useMediaQuery', () => ({ useIsMobile: () => false }));

const toasts: string[] = [];
vi.mock('@/stores/toastStore', () => ({
  toastSuccess: (t: string) => toasts.push(t),
  toastError: (t: string) => toasts.push(t),
}));

import MCPPage from '@/app/(app)/mcp/page';

const json = (body: unknown, status = 200) =>
  Promise.resolve({ status, ok: status < 400, json: () => Promise.resolve(body), clone() { return this; }, headers: new Headers() } as unknown as Response);

const ENTRY = { id: 'row-1', registry_id: 'github-mcp', name: 'GitHub', description: 'd', server_url: 'https://x', auth_type: 'none', categories: [], tools_count: 1, popularity_score: 1, verified: true };

let posts: { url: string; body: any }[];
let installStatus: number;
let entries: unknown[];

beforeEach(() => {
  posts = [];
  installStatus = 201;
  entries = [ENTRY];
  toasts.length = 0;
  localStorage.setItem('access_token', 't');
  global.fetch = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    if (u.endsWith('/registry/install')) {
      posts.push({ url: u, body: JSON.parse(String(init?.body)) });
      return installStatus < 400
        ? json({ data: { id: 'c1', server_name: 'GitHub', server_url: 'https://x', discovered_tools: [], health_status: 'unknown' } }, installStatus)
        : json({ data: null, error: { message: 'Registry entry not found', code: installStatus } }, installStatus);
    }
    if (u.endsWith('/registry/sync')) {
      entries = [ENTRY];
      return json({ data: { synced: 1 } });
    }
    return json({ data: entries });
  }) as unknown as typeof fetch;
});

async function openRegistry() {
  render(<MCPPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Registry' }));
}

describe('MCP registry tab', () => {
  it('installs with the fields the API asks for and says it worked', async () => {
    await openRegistry();
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));
    await waitFor(() => expect(toasts).toContain('GitHub is installed'));
    expect(posts[0].body).toEqual({ registry_id: 'github-mcp', server_name: 'GitHub' });
  });

  it('shows the real error when an install is refused', async () => {
    installStatus = 404;
    await openRegistry();
    fireEvent.click(await screen.findByRole('button', { name: 'Install' }));
    expect(await screen.findByTestId('mcp-registry-error')).toHaveTextContent('GitHub could not be installed. Registry entry not found');
  });

  it('offers Sync on an empty registry and fills the list after it', async () => {
    entries = [];
    await openRegistry();
    fireEvent.click(await screen.findByTestId('mcp-registry-sync-empty'));
    expect(await screen.findByRole('button', { name: 'Install' })).toBeInTheDocument();
    expect(screen.getByTestId('mcp-registry-notice')).toHaveTextContent('Registry synced.');
  });
});
