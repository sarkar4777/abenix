import { currentPath, signInUrl } from '@/lib/auth-redirect';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

type ToastType = 'error' | 'warning' | 'info';
type ToastListener = (message: string, type: ToastType) => void;

const toastListeners: ToastListener[] = [];

export function onApiToast(listener: ToastListener) {
  toastListeners.push(listener);
  return () => {
    const idx = toastListeners.indexOf(listener);
    if (idx >= 0) toastListeners.splice(idx, 1);
  };
}

function emitToast(message: string, type: ToastType) {
  toastListeners.forEach((fn) => fn(message, type));
}

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('access_token');
}

function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('refresh_token');
}

export interface ApiErrorDetail {
  message: string;
  code: number;
  error_code?: string;
  details?: Record<string, unknown>;
}

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  errorDetail?: ApiErrorDetail | null;
  meta: Record<string, unknown> | null;
}

interface FetchOptions extends Omit<RequestInit, 'headers'> {
  headers?: Record<string, string>;
  silent?: boolean;
  throwOnError?: boolean;
}

export class ApiError extends Error {
  status: number;
  errorCode?: string;
  details?: Record<string, unknown>;
  constructor(detail: ApiErrorDetail) {
    super(detail.message);
    this.name = 'ApiError';
    this.status = detail.code;
    this.errorCode = detail.error_code;
    this.details = detail.details;
  }
}

export const BUSY_MESSAGE = 'The server is busy right now. Try again in a moment.';
export const UNREACHABLE_MESSAGE = "Can't reach the server. Check your connection and try again.";

export function isTransientError(detail: { code?: number; status?: number; error_code?: string; errorCode?: string } | null | undefined): boolean {
  if (!detail) return false;
  const code = detail.code ?? detail.status;
  const ec = detail.error_code ?? detail.errorCode;
  return ec === 'NETWORK_ERROR' || ec === 'SERVER_BUSY' || code === 0 || code === 502 || code === 503 || code === 504;
}

const RETRY_STATUSES = new Set([502, 503, 504]);
let retryDelays = [500, 1500, 3500];

export function setApiRetryDelays(delays: number[]) {
  retryDelays = delays;
}

export type ApiConnection = 'ok' | 'reconnecting';
type ConnectionListener = (state: ApiConnection) => void;
const connectionListeners = new Set<ConnectionListener>();
let connection: ApiConnection = 'ok';

export function getApiConnection(): ApiConnection {
  return connection;
}

export function onApiConnection(listener: ConnectionListener) {
  connectionListeners.add(listener);
  return () => {
    connectionListeners.delete(listener);
  };
}

export function setApiConnection(state: ApiConnection) {
  if (state === connection) return;
  connection = state;
  connectionListeners.forEach((fn) => fn(state));
}

const BUSY_CODES = new Set(['BUSY', 'SERVER_BUSY', 'SERVICE_UNAVAILABLE', 'GATEWAY_TIMEOUT', 'BAD_GATEWAY', 'OVERLOADED']);

// a 502-504 from a proxy or a starved pool is busy, one with its own error code is a real answer
export async function isBusyResponse(r: Response): Promise<boolean> {
  if (!RETRY_STATUSES.has(r.status)) return false;
  let body: any = null;
  try { body = await r.clone().json(); } catch { return true; }
  const err = body && typeof body === 'object' ? body.error : null;
  const code = err && typeof err === 'object' ? err.error_code : null;
  if (code) return BUSY_CODES.has(String(code).toUpperCase());
  const msg = typeof err === 'string' ? err : err && typeof err === 'object' ? String(err.message ?? '') : String(body?.detail ?? '');
  return !msg || /busy|unavailable|timed? ?out|bad gateway|overload/i.test(msg);
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

export type RefreshResult =
  | { kind: 'ok'; token: string }
  | { kind: 'invalid' }
  | { kind: 'unavailable' };

let refreshing: Promise<RefreshResult> | null = null;

async function doRefresh(): Promise<RefreshResult> {
  const rt = getRefreshToken();
  if (!rt) return { kind: 'invalid' };
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
  } catch {
    return { kind: 'unavailable' };
  }
  if (!res || res.status >= 500 || res.status === 429) return { kind: 'unavailable' };
  let json: any = {};
  try { json = await res.json(); } catch { /* empty body */ }
  const newToken = res.ok ? json?.data?.access_token || null : null;
  if (!newToken) return { kind: 'invalid' };
  localStorage.setItem('access_token', newToken);
  if (json.data?.refresh_token) localStorage.setItem('refresh_token', json.data.refresh_token);
  return { kind: 'ok', token: newToken };
}

// one refresh at a time, every caller waits on the same answer
export function refreshSession(): Promise<RefreshResult> {
  if (!refreshing) {
    refreshing = doRefresh().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

const MUTATION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {},
): Promise<ApiResponse<T>> {
  const { silent, throwOnError, ...fetchOpts } = options;
  const method = String(fetchOpts.method || 'GET').toUpperCase();
  const isMutation = MUTATION_METHODS.has(method);
  const idempotent = method === 'GET' || method === 'HEAD';
  const shouldThrow = throwOnError ?? isMutation;
  const token = getToken();
  // SWR can fire before login stores the token, skip rather than send a doomed 401
  const isPublicPath =
    path.startsWith('/api/auth/') ||
    path.startsWith('/api/health') ||
    path === '/api/public-settings';
  if (!token && !isPublicPath && typeof window !== 'undefined') {
    const detail: ApiErrorDetail = {
      message: 'unauthenticated',
      code: 401,
      error_code: 'NO_TOKEN',
    };
    if (shouldThrow) throw new ApiError(detail);
    return { data: null, error: 'unauthenticated', errorDetail: detail, meta: null };
  }
  const headers: Record<string, string> = { ...fetchOpts.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (fetchOpts.body && typeof fetchOpts.body === 'string') {
    headers['Content-Type'] = 'application/json';
  }

  const fail = (detail: ApiErrorDetail, toast: ToastType | null): ApiResponse<T> => {
    if (toast && !silent) emitToast(detail.message, toast);
    if (shouldThrow) throw new ApiError(detail);
    return { data: null, error: detail.message, errorDetail: detail, meta: null };
  };
  // reads leave the reconnecting banner to speak, writes get a toast
  const busyToast: ToastType | null = isMutation ? 'error' : null;

  const send = async (): Promise<Response | Error> => {
    const attempts = idempotent ? retryDelays.length + 1 : 1;
    let last: Response | Error = new Error('Network error');
    for (let i = 0; i < attempts; i++) {
      if (i > 0) await sleep(retryDelays[i - 1]);
      try {
        const r = await fetch(`${API_URL}${path}`, { ...fetchOpts, headers });
        if (!r) throw new Error('Network error');
        last = r;
        if (!(await isBusyResponse(r))) return r;
      } catch (err) {
        if ((err as { name?: string } | null)?.name === 'AbortError') throw err;
        last = err instanceof Error ? err : new Error('Network error');
      }
      setApiConnection('reconnecting');
    }
    return last;
  };

  let res = await send();
  if (res instanceof Error) {
    return fail({ message: UNREACHABLE_MESSAGE, code: 0, error_code: 'NETWORK_ERROR' }, busyToast);
  }

  if (res.status === 401 && token) {
    const refreshed = await refreshSession();
    if (refreshed.kind === 'ok') {
      headers['Authorization'] = `Bearer ${refreshed.token}`;
      res = await send();
      if (res instanceof Error) {
        return fail({ message: UNREACHABLE_MESSAGE, code: 0, error_code: 'NETWORK_ERROR' }, busyToast);
      }
    } else if (refreshed.kind === 'unavailable') {
      // a busy refresh is not a sign-out, keep the tokens and let the caller retry
      setApiConnection('reconnecting');
      return fail({ message: BUSY_MESSAGE, code: 503, error_code: 'SERVER_BUSY' }, busyToast);
    } else {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      if (typeof window !== 'undefined') {
        window.location.href = signInUrl(currentPath(), { expired: true });
      }
      return fail({ message: 'Session expired', code: 401, error_code: 'SESSION_EXPIRED' }, null);
    }
  }

  if (await isBusyResponse(res)) {
    return fail({ message: BUSY_MESSAGE, code: res.status, error_code: 'SERVER_BUSY' }, busyToast);
  }
  setApiConnection('ok');

  let json: any = {};
  try { json = await res.json(); } catch { /* non-JSON 204 etc. */ }

  if (res.status === 429) {
    const retryAfter = res.headers?.get?.('Retry-After');
    const msg = retryAfter
      ? `Too many requests. Try again in ${retryAfter} s.`
      : 'Too many requests. Please slow down.';
    return fail({ message: msg, code: 429, error_code: 'RATE_LIMITED' }, 'warning');
  }

  // Non-2xx, structured envelope if the backend supplied one
  if (!res.ok) {
    const errObj = (json && typeof json.error === 'object' && json.error) ? json.error : null;
    const msg = (errObj?.message as string)
      || (typeof json?.error === 'string' ? json.error : null)
      || `Server error (${res.status})`;
    const detail: ApiErrorDetail = {
      message: msg,
      code: errObj?.code ?? res.status,
      error_code: errObj?.error_code,
      details: errObj?.details,
    };
    return fail(detail, res.status >= 500 ? 'error' : null);
  }

  return {
    data: json.data ?? null,
    error: null,
    errorDetail: null,
    meta: json.meta ?? null,
  };
}

export { API_URL };
