import { act, render, screen, waitFor } from '@testing-library/react';
import {
  apiFetch,
  BUSY_MESSAGE,
  getApiConnection,
  isTransientError,
  onApiToast,
  setApiConnection,
  setApiRetryDelays,
} from '@/lib/api-client';
import { AuthProvider, loadMe, setAuthBackoff, useAuth } from '@/contexts/AuthContext';
import { explainTelemetryError, describeTest } from '@/lib/telemetry/errors';

const mockFetch = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const original = window.location;
let loc: { href: string; pathname: string; search: string; hash: string };

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
  setApiRetryDelays([0, 0, 0]);
  setAuthBackoff([5, 5, 5]);
  setApiConnection('ok');
  loc = { href: '', pathname: '/telemetry', search: '', hash: '' };
  Object.defineProperty(window, 'location', { configurable: true, value: loc });
});

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: original });
});

describe('api client under a busy API', () => {
  it('retries an idempotent GET on 503 and succeeds', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch
      .mockResolvedValueOnce(json(503, { error: 'BUSY' }))
      .mockResolvedValueOnce(json(502, {}))
      .mockResolvedValueOnce(json(200, { data: { ok: 1 } }));
    const seen: string[] = [];
    const off = onApiToast((m) => seen.push(m));
    const res = await apiFetch<{ ok: number }>('/api/telemetry/devices');
    off();
    expect(res.data).toEqual({ ok: 1 });
    expect(mockFetch).toHaveBeenCalledTimes(3);
    expect(seen).toEqual([]);
    expect(getApiConnection()).toBe('ok');
  });

  it('gives up after the retries with a plain busy error and no toast for reads', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValue(json(504, {}));
    const seen: string[] = [];
    const off = onApiToast((m) => seen.push(m));
    const res = await apiFetch('/api/telemetry/health');
    off();
    expect(mockFetch).toHaveBeenCalledTimes(4);
    expect(res.errorDetail?.error_code).toBe('SERVER_BUSY');
    expect(res.error).toBe(BUSY_MESSAGE);
    expect(seen).toEqual([]);
    expect(getApiConnection()).toBe('reconnecting');
    expect(isTransientError(res.errorDetail)).toBe(true);
  });

  it('retries a network error on GET', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(json(200, { data: [] }));
    const res = await apiFetch('/api/agents');
    expect(res.data).toEqual([]);
  });

  it('never retries a mutation, and toasts in plain words', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValue(json(503, { error: 'BUSY' }));
    const seen: string[] = [];
    const off = onApiToast((m) => seen.push(m));
    await expect(apiFetch('/api/telemetry/rules', { method: 'POST', body: '{}' })).rejects.toThrow(BUSY_MESSAGE);
    off();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(seen).toEqual([BUSY_MESSAGE]);
  });

  it('keeps the session when the refresh itself is busy', async () => {
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'r');
    mockFetch.mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(503, {}));
    const res = await apiFetch('/api/agents');
    expect(res.errorDetail?.error_code).toBe('SERVER_BUSY');
    expect(localStorage.getItem('access_token')).toBe('old');
    expect(loc.href).toBe('');
  });

  it('signs out only when the refresh is refused', async () => {
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'r');
    mockFetch.mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(401, { error: 'bad refresh' }));
    const res = await apiFetch('/api/agents');
    expect(res.errorDetail?.error_code).toBe('SESSION_EXPIRED');
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(loc.href).toContain('session=expired');
  });

  it('shares one refresh between parallel 401s', async () => {
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'r');
    mockFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/refresh')) return json(200, { data: { access_token: 'new' } });
      const auth = (init?.headers as Record<string, string>)?.Authorization;
      return auth === 'Bearer new' ? json(200, { data: 1 }) : json(401, {});
    });
    const [a, b] = await Promise.all([apiFetch('/api/a'), apiFetch('/api/b')]);
    expect(a.data).toBe(1);
    expect(b.data).toBe(1);
    expect(mockFetch.mock.calls.filter(([u]) => String(u).endsWith('/api/auth/refresh'))).toHaveLength(1);
  });
});

describe('loadMe', () => {
  it('reads a 503 as unavailable, not signed out', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValueOnce(json(503, { error: 'BUSY' }));
    expect(await loadMe()).toEqual({ kind: 'unavailable' });
  });
  it('reads a network error as unavailable', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    expect(await loadMe()).toEqual({ kind: 'unavailable' });
  });
  it('refreshes on 401 and loads the user', async () => {
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'r');
    mockFetch
      .mockResolvedValueOnce(json(401, {}))
      .mockResolvedValueOnce(json(200, { data: { access_token: 'new' } }))
      .mockResolvedValueOnce(json(200, { data: { user: { id: 'u1' } } }));
    const out = await loadMe();
    expect(out.kind).toBe('user');
    expect(localStorage.getItem('access_token')).toBe('new');
  });
  it('signs out on a 401 whose refresh is refused', async () => {
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'r');
    mockFetch.mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(401, {}));
    expect(await loadMe()).toEqual({ kind: 'signed_out' });
  });
  it('stays signed in when a 401 meets a busy refresh', async () => {
    localStorage.setItem('access_token', 'old');
    localStorage.setItem('refresh_token', 'r');
    mockFetch.mockResolvedValueOnce(json(401, {})).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    expect(await loadMe()).toEqual({ kind: 'unavailable' });
  });
});

function Probe() {
  const { user, loading, reconnecting } = useAuth();
  return <p data-testid="probe">{loading ? (reconnecting ? 'reconnecting' : 'loading') : user ? `user:${user.id}` : 'signed-out'}</p>;
}

describe('AuthProvider', () => {
  it('rides out a busy API and keeps the user signed in', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch
      .mockResolvedValueOnce(json(503, {}))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(json(200, { data: { user: { id: 'u1' } } }));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('reconnecting'));
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('user:u1'));
    expect(localStorage.getItem('access_token')).toBe('tok');
  });

  it('signs out on a real 401 after the refresh fails', async () => {
    localStorage.setItem('access_token', 'tok');
    localStorage.setItem('refresh_token', 'r');
    mockFetch.mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(401, {}));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('probe').textContent).toBe('signed-out'));
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('ends loading at once with no token', async () => {
    await act(async () => {
      render(<AuthProvider><Probe /></AuthProvider>);
    });
    expect(screen.getByTestId('probe').textContent).toBe('signed-out');
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe('telemetry wording for a busy API', () => {
  it('says busy and retrying for loads, did not go through for writes', () => {
    expect(explainTelemetryError({ status: 503, errorCode: 'SERVER_BUSY' }, 'load')).toMatch(/busy right now. Retrying/);
    expect(explainTelemetryError({ status: 503 }, 'save')).toMatch(/did not go through/);
  });
  it('gives a Kafka TLS failure Kafka words', () => {
    const t = describeTest({ ok: false, connected: false, messages: 0, topics_seen: [], error: 'SSL handshake failed' }, 'kafka-1:9093', 'kafka').text;
    expect(t).toMatch(/SASL_SSL/);
    expect(t).not.toMatch(/mqtts/);
    const m = describeTest({ ok: false, connected: false, messages: 0, topics_seen: [], error: 'SSL handshake failed' }, 'mqtts://b:8883').text;
    expect(m).toMatch(/mqtts/);
  });
});

describe('real answers on 502 and 503 are not busy', () => {
  it('passes a coded 502 straight through without retrying', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValueOnce(json(502, { error: { message: 'Connection refused', code: 502, error_code: 'BROKER_UNREACHABLE' } }));
    const res = await apiFetch('/api/telemetry/testbed');
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(res.errorDetail?.error_code).toBe('BROKER_UNREACHABLE');
  });
  it('treats the pool BUSY envelope as busy', async () => {
    localStorage.setItem('access_token', 'tok');
    mockFetch.mockResolvedValue(json(503, { error: { message: 'The service is busy, retry shortly.', code: 503, error_code: 'BUSY' } }));
    const res = await apiFetch('/api/x');
    expect(mockFetch).toHaveBeenCalledTimes(4);
    expect(res.errorDetail?.error_code).toBe('SERVER_BUSY');
  });
});
