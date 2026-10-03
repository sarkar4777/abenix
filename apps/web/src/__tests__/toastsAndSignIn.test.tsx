import { act, render, screen, within } from '@testing-library/react';
import { ToastProvider } from '@/components/ToastProvider';
import { apiFetch } from '@/lib/api-client';
import { safeReturnPath, signInUrl } from '@/lib/auth-redirect';
import { useToastStore } from '@/stores/toastStore';

const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
  useToastStore.setState({ toasts: [] });
});

describe('ToastProvider', () => {
  it('shows a server error raised by the API client', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValueOnce(
      jsonResponse(500, { error: { message: 'Database is unavailable', code: 500 } }),
    );
    render(
      <ToastProvider>
        <p>page</p>
      </ToastProvider>,
    );
    await act(async () => {
      await apiFetch('/api/agents');
    });
    const region = screen.getByRole('region', { name: 'Notifications' });
    expect(within(region).getByText('Database is unavailable')).toBeInTheDocument();
  });

  it('stays quiet for silent requests', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValueOnce(jsonResponse(500, { error: 'boom' }));
    render(<ToastProvider>{null}</ToastProvider>);
    await act(async () => {
      await apiFetch('/api/agents', { silent: true });
    });
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

describe('expired session redirect', () => {
  const original = window.location;

  afterEach(() => {
    Object.defineProperty(window, 'location', { configurable: true, value: original });
  });

  it('sends the browser to the sign-in page with a return path', async () => {
    const loc = { href: '', pathname: '/agents/42', search: '?tab=runs', hash: '' };
    Object.defineProperty(window, 'location', { configurable: true, value: loc });
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'stale');
    mockFetch
      .mockResolvedValueOnce(jsonResponse(401, { error: 'expired' }))
      .mockResolvedValueOnce(jsonResponse(401, { data: null, error: 'bad refresh' }));

    const res = await apiFetch('/api/agents');

    expect(res.errorDetail?.error_code).toBe('SESSION_EXPIRED');
    expect(loc.href).toBe('/?return_to=%2Fagents%2F42%3Ftab%3Druns&session=expired');
    expect(loc.href.startsWith('/login')).toBe(false);
    expect(localStorage.getItem('access_token')).toBeNull();
  });
});

describe('auth-redirect helpers', () => {
  it('only accepts same-site relative return paths', () => {
    expect(safeReturnPath('/settings/webhooks')).toBe('/settings/webhooks');
    expect(safeReturnPath('https://evil.example')).toBe('/dashboard');
    expect(safeReturnPath('//evil.example')).toBe('/dashboard');
    expect(safeReturnPath('/\\evil.example')).toBe('/dashboard');
    expect(safeReturnPath(null)).toBe('/dashboard');
    expect(safeReturnPath('/')).toBe('/dashboard');
  });

  it('builds the landing page sign-in url', () => {
    expect(signInUrl()).toBe('/');
    expect(signInUrl('/')).toBe('/');
    expect(signInUrl('/team')).toBe('/?return_to=%2Fteam');
  });
});
