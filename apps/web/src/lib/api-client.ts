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

let isRefreshing = false;
let refreshQueue: Array<(token: string | null) => void> = [];

async function refreshAccessToken(): Promise<string | null> {
  if (isRefreshing) {
    return new Promise((resolve) => refreshQueue.push(resolve));
  }
  isRefreshing = true;
  const rt = getRefreshToken();
  if (!rt) {
    isRefreshing = false;
    refreshQueue.forEach((cb) => cb(null));
    refreshQueue = [];
    return null;
  }
  try {
    const res = await fetch(`${API_URL}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
    const json = await res.json();
    const newToken = json.data?.access_token || null;
    if (newToken) {
      localStorage.setItem('access_token', newToken);
      if (json.data?.refresh_token) {
        localStorage.setItem('refresh_token', json.data.refresh_token);
      }
    }
    isRefreshing = false;
    refreshQueue.forEach((cb) => cb(newToken));
    refreshQueue = [];
    return newToken;
  } catch {
    isRefreshing = false;
    refreshQueue.forEach((cb) => cb(null));
    refreshQueue = [];
    return null;
  }
}

const MUTATION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {},
): Promise<ApiResponse<T>> {
  const { silent, throwOnError, ...fetchOpts } = options;
  const shouldThrow = throwOnError ?? MUTATION_METHODS.has(
    String(fetchOpts.method || 'GET').toUpperCase()
  );
  const token = getToken();
  // Skip the request entirely when no token is present. SWR sometimes
  // fires the fetcher before the login flow stores the access_token,
  // and an unauthenticated request to a protected endpoint returns 401
  // — which the browser surfaces as a CORS error if the upstream did
  // not attach the right headers. Short-circuiting here avoids the
  // race and the misleading console error.
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

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...fetchOpts, headers });
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Network error';
    if (!silent) emitToast(`Connection failed: ${msg}`, 'error');
    const detail: ApiErrorDetail = { message: msg, code: 0, error_code: 'NETWORK_ERROR' };
    if (shouldThrow) throw new ApiError(detail);
    return { data: null, error: msg, errorDetail: detail, meta: null };
  }

  // Auto-refresh on 401
  if (res.status === 401 && token) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`;
      res = await fetch(`${API_URL}${path}`, { ...fetchOpts, headers });
    } else {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      if (typeof window !== 'undefined') {
        window.location.href = signInUrl(currentPath(), { expired: true });
      }
      const detail: ApiErrorDetail = { message: 'Session expired', code: 401, error_code: 'SESSION_EXPIRED' };
      if (shouldThrow) throw new ApiError(detail);
      return { data: null, error: 'Session expired', errorDetail: detail, meta: null };
    }
  }

  let json: any = {};
  try { json = await res.json(); } catch { /* non-JSON 204 etc. */ }

  // Rate limit
  if (res.status === 429) {
    const retryAfter = res.headers.get('Retry-After');
    const msg = retryAfter
      ? `Rate limited. Try again in ${retryAfter}s.`
      : 'Too many requests. Please slow down.';
    if (!silent) emitToast(msg, 'warning');
    const detail: ApiErrorDetail = { message: msg, code: 429, error_code: 'RATE_LIMITED' };
    if (shouldThrow) throw new ApiError(detail);
    return { data: null, error: msg, errorDetail: detail, meta: null };
  }

  // Non-2xx — structured envelope if backend supplied one, else synthesise.
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
    if (res.status >= 500 && !silent) emitToast(msg, 'error');
    if (shouldThrow) throw new ApiError(detail);
    return { data: null, error: msg, errorDetail: detail, meta: null };
  }

  return {
    data: json.data ?? null,
    error: null,
    errorDetail: null,
    meta: json.meta ?? null,
  };
}

export { API_URL };
