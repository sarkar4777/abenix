import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import AuthCard from '@/components/landing/AuthCard';
import { retentionProblem } from '@/lib/settings-validation';

function respond(body: unknown, status = 200) {
  return Promise.resolve({ status, json: () => Promise.resolve(body) } as Response);
}

describe('sign-in card', () => {
  let calls: { url: string; body: any }[];

  beforeEach(() => {
    calls = [];
    localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  function mockFetch(routes: Record<string, () => Promise<Response>>) {
    global.fetch = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      const u = String(url);
      calls.push({ url: u, body: init?.body ? JSON.parse(String(init.body)) : null });
      const key = Object.keys(routes).find((k) => u.endsWith(k));
      return key ? routes[key]() : respond({ data: { providers: [] } });
    }) as unknown as typeof fetch;
  }

  it('asks for the app code when two-step sign-in is on, and sends it with the challenge', async () => {
    mockFetch({
      '/api/auth/login': () => respond({ data: { two_factor_required: true, challenge: 'ch-1', email: 'a@b.dev' } }),
      '/api/auth/login/2fa': () => respond({ data: null, error: { message: 'That code did not match.' } }, 401),
    });
    render(<AuthCard />);
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'a@b.dev' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'secret-pw' } });
    fireEvent.click(screen.getByTestId('auth-submit'));
    await screen.findByTestId('auth-2fa-form');
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(screen.getByText(/Two-step sign-in is on for a@b.dev/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Code from your app'), { target: { value: '123456' } });
    fireEvent.click(screen.getByTestId('auth-2fa-submit'));
    await screen.findByText('That code did not match.');
    const sent = calls.find((c) => c.url.endsWith('/api/auth/login/2fa'));
    expect(sent?.body).toEqual({ challenge: 'ch-1', code: '123456' });
  });

  it('says plainly when no workspace uses SSO for the domain', async () => {
    mockFetch({
      '/api/auth/sso/discover': () =>
        respond({ data: null, error: { message: 'No workspace signs in with single sign-on for x.dev. Use your password instead.' } }, 404),
    });
    render(<AuthCard />);
    fireEvent.click(screen.getByTestId('auth-sso-toggle'));
    fireEvent.change(screen.getByLabelText('Work email'), { target: { value: 'me@x.dev' } });
    fireEvent.click(screen.getByTestId('auth-sso-submit'));
    await screen.findByText(/Use your password instead/);
    expect(calls.find((c) => c.url.endsWith('/api/auth/sso/discover'))?.body).toEqual({ email: 'me@x.dev' });
  });

  it('shows the SSO error the callback sent back and the reset notice', async () => {
    mockFetch({});
    window.history.replaceState({}, '', '/?sso_error=Ask%20an%20admin&reset=done&email=a%40b.dev');
    render(<AuthCard />);
    await waitFor(() => expect(screen.getByText('Ask an admin')).toBeTruthy());
    expect(screen.getByTestId('auth-notice').textContent).toContain('password was changed');
    expect((screen.getByLabelText('Email address') as HTMLInputElement).value).toBe('a@b.dev');
  });

  it('links Forgot password to the real reset page with the email filled in', async () => {
    mockFetch({});
    render(<AuthCard />);
    fireEvent.change(screen.getByLabelText('Email address'), { target: { value: 'a@b.dev' } });
    expect(screen.getByTestId('auth-forgot-link').getAttribute('href')).toBe('/auth/forgot?email=a%40b.dev');
  });
});

describe('retention days', () => {
  it('lets half-typed values through to the field and explains what is wrong', () => {
    expect(retentionProblem('4', 365)).toBe('Use 365 days or more');
    expect(retentionProblem('400', 365)).toBeNull();
    expect(retentionProblem('', 7)).toBe('Type a whole number of days');
    expect(retentionProblem('3.5', 7)).toBe('Type a whole number of days');
  });
});

describe('quota limits', () => {
  it('accepts blank, zero and positive values and explains the rest', async () => {
    const { quotaProblem } = await import('@/lib/settings-validation');
    expect(quotaProblem('', true)).toBeNull();
    expect(quotaProblem('0', true)).toBeNull();
    expect(quotaProblem('250000', true)).toBeNull();
    expect(quotaProblem('-5', false)).toBe('Cannot be negative');
    expect(quotaProblem('1.5', true)).toBe('Use a whole number');
    expect(quotaProblem('ten', false)).toBe('Type a number, or leave it blank');
    expect(quotaProblem('12.50', false)).toBeNull();
  });
});
