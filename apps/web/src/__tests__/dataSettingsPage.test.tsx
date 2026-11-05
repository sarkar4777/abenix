import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { dlpPatternProblem } from '@/lib/settings-validation';

const auth: { user: { role: string } | null } = { user: { role: 'admin' } };

vi.mock('next/link', () => ({
  default: ({ href, children, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('@/hooks/usePageTitle', () => ({ usePageTitle: () => {} }));

import DataSettingsPage from '@/app/(app)/settings/data/page';

const json = (body: unknown, status = 200) =>
  Promise.resolve({ status, ok: status < 400, json: () => Promise.resolve(body), clone() { return this; }, headers: new Headers() } as unknown as Response);

let puts: { url: string; body: any }[];
let putStatus: Record<string, number>;

beforeEach(() => {
  auth.user = { role: 'admin' };
  puts = [];
  putStatus = {};
  localStorage.setItem('access_token', 't');
  global.fetch = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    if (init?.method === 'PUT') {
      const body = JSON.parse(String(init.body));
      puts.push({ url: u, body });
      const key = u.endsWith('/dlp') ? 'dlp' : 'retention';
      if (putStatus[key]) return json({ data: null, error: { message: 'Refused by the server', code: putStatus[key] } }, putStatus[key]);
      return json({ data: body });
    }
    if (u.endsWith('/api/settings/dlp')) return json({ data: { mode: 'mask', enabled: true, custom_patterns: { order: 'ORD-\\d+' } } });
    return json({ data: { execution_retention_days: 90, message_retention_days: 365, audit_log_retention_days: 730 } });
  }) as unknown as typeof fetch;
});

describe('Data and DLP settings', () => {
  it('shows the saved values and the help for the mode', async () => {
    render(<DataSettingsPage />);
    expect(await screen.findByTestId('dlp-enabled')).toBeChecked();
    expect(screen.getByTestId('dlp-mode')).toHaveValue('mask');
    expect(screen.getByTestId('dlp-mode-help')).toHaveTextContent('EMAIL_MASKED');
    expect(screen.getByTestId('ret-audit_log_retention_days')).toHaveValue('730');
    expect(screen.getByTestId('dlp-pattern-regex')).toHaveValue('ORD-\\d+');
  });

  it('refuses a retention below the minimum before it reaches the API', async () => {
    render(<DataSettingsPage />);
    const audit = await screen.findByTestId('ret-audit_log_retention_days');
    fireEvent.change(audit, { target: { value: '4' } });
    expect(screen.getByText('Use 365 days or more')).toBeInTheDocument();
    expect(screen.getByTestId('data-settings-save')).toBeDisabled();
    fireEvent.change(audit, { target: { value: '400' } });
    expect(screen.getByTestId('data-settings-save')).toBeEnabled();
  });

  it('keeps custom patterns on a DLP save and leaves retention alone', async () => {
    render(<DataSettingsPage />);
    fireEvent.change(await screen.findByTestId('dlp-mode'), { target: { value: 'block' } });
    fireEvent.click(screen.getByTestId('data-settings-save'));
    await screen.findByTestId('data-settings-saved');
    expect(puts).toHaveLength(1);
    expect(puts[0].url).toMatch(/\/api\/settings\/dlp$/);
    expect(puts[0].body).toEqual({ enabled: true, mode: 'block', custom_patterns: { order: 'ORD-\\d+' } });
  });

  it('says saved even when nothing changed, so a repeat save is not a dead end', async () => {
    render(<DataSettingsPage />);
    await screen.findByTestId('dlp-enabled');
    fireEvent.click(screen.getByTestId('data-settings-save'));
    await screen.findByTestId('data-settings-saved');
    expect(puts).toHaveLength(0);
  });

  it('names the part that failed and does not claim it saved', async () => {
    putStatus.retention = 400;
    render(<DataSettingsPage />);
    fireEvent.click(await screen.findByTestId('dlp-enabled'));
    fireEvent.change(screen.getByTestId('ret-message_retention_days'), { target: { value: '100' } });
    fireEvent.click(screen.getByTestId('data-settings-save'));
    const err = await screen.findByTestId('data-settings-error');
    expect(err).toHaveTextContent('Retention was not saved. Refused by the server');
    expect(screen.queryByTestId('data-settings-saved')).toBeNull();
    expect(puts).toHaveLength(2);
  });

  it('is read only for a member', async () => {
    auth.user = { role: 'user' };
    render(<DataSettingsPage />);
    expect(await screen.findByTestId('dlp-enabled')).toBeDisabled();
    expect(screen.getByTestId('data-settings-readonly')).toBeInTheDocument();
    expect(screen.getByTestId('data-settings-save')).toBeDisabled();
    expect(screen.getByTestId('ret-message_retention_days')).toBeDisabled();
    expect(screen.queryByTestId('dlp-pattern-add')).toBeNull();
  });

  it('shows a load failure with a retry and offers no form that could overwrite settings', async () => {
    global.fetch = vi.fn(() => json({ data: null, error: { message: 'Not allowed here', code: 403 } }, 403)) as unknown as typeof fetch;
    render(<DataSettingsPage />);
    expect(await screen.findByTestId('data-settings-load-error')).toHaveTextContent('Not allowed here');
    expect(screen.queryByTestId('dlp-enabled')).toBeNull();
    await waitFor(() => expect(screen.getByTestId('data-settings-save')).toBeDisabled());
  });
});

describe('custom DLP pattern check', () => {
  it('accepts the Python forms the scanner understands', () => {
    expect(dlpPatternProblem('order', '(?i)ord-(?P<n>\\d+)')).toBeNull();
  });
  it('catches what the scanner would quietly skip', () => {
    expect(dlpPatternProblem('order', 'ORD-(')).toBe('This is not a valid regular expression');
    expect(dlpPatternProblem('', 'x')).toBe('Give this pattern a name');
    expect(dlpPatternProblem('Order', 'x', ['order'])).toBe('Another pattern has this name');
  });
});
