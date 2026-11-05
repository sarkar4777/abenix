import { act, fireEvent, render, screen } from '@testing-library/react';
import { PLAYGROUND_REFUSED, playgroundRefusal } from '@/lib/playground';

const state: { capabilities: string[] } = { capabilities: [] };

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => ({ perms: { capabilities: state.capabilities }, loading: false }) };
});
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));
vi.mock('@/lib/fetch-all-agents', () => ({
  fetchAllAgents: () => Promise.resolve({ agents: [{ id: 'a1', name: 'A', slug: 'a' }], total: 1 }),
}));

import LoadPlaygroundPage from '@/app/(app)/load-playground/page';

const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });

describe('playground refusal text', () => {
  it('reads the reason the API gave for a switched off deployment', async () => {
    const off = 'Running code in the playground is turned off on this deployment, because the code runs inside the API process.';
    expect(await playgroundRefusal(res(403, { data: null, error: { message: off } }))).toBe(off);
  });
  it('never says admins only', async () => {
    expect(await playgroundRefusal(new Response('nope', { status: 403 }))).toBe(PLAYGROUND_REFUSED);
    expect(PLAYGROUND_REFUSED).not.toMatch(/only admins/i);
  });
  it('lets a good run through', async () => {
    expect(await playgroundRefusal(new Response('ok', { status: 200 }))).toBeNull();
  });
});

describe('load playground', () => {
  beforeEach(() => {
    localStorage.setItem('access_token', 't');
    global.fetch = vi.fn((url: RequestInfo | URL) => {
      const u = String(url);
      if (u.endsWith('/generate')) return Promise.resolve(res(200, { data: { code: 'print(1)', model_used: 'm' } }));
      return Promise.resolve(res(403, { data: null, error: { message: 'Running code in the playground is turned off on this deployment.' } }));
    }) as unknown as typeof fetch;
  });

  async function generate() {
    render(<LoadPlaygroundPage />);
    await act(async () => { await Promise.resolve(); });
    const btn = await screen.findByRole('button', { name: /generate/i });
    await screen.findByRole('option', { name: /^A/ });
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'a1' } });
    fireEvent.click(btn);
    await screen.findByText('print(1)');
  }

  it('hides Run and says why without the capability', async () => {
    state.capabilities = ['agents.view'];
    await generate();
    expect(screen.queryByRole('button', { name: 'Run' })).toBeNull();
    expect(screen.getByTestId('load-run-permission')).toHaveTextContent('Run playground code permission');
    expect(document.body.textContent).not.toMatch(/only admins/i);
  });

  it('shows the switched off reason when a holder runs it', async () => {
    state.capabilities = ['playground.execute'];
    await generate();
    fireEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findByText(/turned off on this deployment/)).toBeInTheDocument();
  });
});
