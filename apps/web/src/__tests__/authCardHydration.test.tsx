import { act, render, screen } from '@testing-library/react';
import { hydrateRoot } from 'react-dom/client';
import { renderToString } from 'react-dom/server';
import AuthCard, { demoLoginVisible } from '@/components/landing/AuthCard';

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/');
  global.fetch = vi.fn(() => Promise.resolve({ status: 200, json: () => Promise.resolve({ data: { providers: [] } }) } as Response)) as unknown as typeof fetch;
});
afterEach(() => vi.unstubAllEnvs());

describe('sign-in form before hydration', () => {
  it('keeps what was typed while the page was still loading', async () => {
    const box = document.createElement('div');
    document.body.appendChild(box);
    box.innerHTML = renderToString(<AuthCard />);
    (box.querySelector('#auth-email') as HTMLInputElement).value = 'typed@example.com';
    (box.querySelector('#auth-password') as HTMLInputElement).value = 'typed-password';

    let root!: ReturnType<typeof hydrateRoot>;
    await act(async () => {
      root = hydrateRoot(box, <AuthCard />);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 250));
    });
    expect((box.querySelector('#auth-email') as HTMLInputElement).value).toBe('typed@example.com');
    expect((box.querySelector('#auth-password') as HTMLInputElement).value).toBe('typed-password');
    await act(async () => root.unmount());
    box.remove();
  });
});

describe('demo sign-in buttons', () => {
  it('are for dev and for builds that ask for them', () => {
    expect(demoLoginVisible('development', undefined)).toBe(true);
    expect(demoLoginVisible('production', undefined)).toBe(false);
    expect(demoLoginVisible('production', 'true')).toBe(true);
    expect(demoLoginVisible('production', 'false')).toBe(false);
  });

  it('stay off the page in a production build', () => {
    vi.stubEnv('NODE_ENV', 'production');
    render(<AuthCard />);
    expect(screen.queryByTestId('auth-demo-login')).toBeNull();
    expect(screen.queryByText('Admin Demo')).toBeNull();
  });

  it('show up in development', () => {
    vi.stubEnv('NODE_ENV', 'development');
    render(<AuthCard />);
    expect(screen.getByText('Admin Demo')).toBeInTheDocument();
  });
});
