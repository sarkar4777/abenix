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

interface ApiResponse<T> {
  data: T | null;
  error: string | null;
  meta: Record<string, unknown> | null;
}

interface FetchOptions extends Omit<RequestInit, 'headers'> {
  headers?: Record<string, string>;
  silent?: boolean; // suppress toast notifications
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

export async function apiFetch<T = unknown>(
  path: string,
  options: FetchOptions = {},
): Promise<ApiResponse<T>> {
  const { silent, ...fetchOpts } = options;
  const token = getToken();
  const headers: Record<string, string> = { ...fetchOpts.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (fetchOpts.body && typeof fetchOpts.body === 'string') {
    headers['Content-Type'] = 'application/json';
  }

  try {
    let res = await fetch(`${API_URL}${path}`, { ...fetchOpts, headers });

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
          window.location.href = '/login';
        }
        return { data: null, error: 'Session expired', meta: null };
      }
    }

    const json = await res.json();

    // Handle rate limiting
    if (res.status === 429) {
      const retryAfter = res.headers.get('Retry-After');
      const msg = retryAfter
        ? `Rate limited. Try again in ${retryAfter}s.`
        : 'Too many requests. Please slow down.';
      if (!silent) emitToast(msg, 'warning');
      return { data: null, error: msg, meta: null };
    }

    // Handle server errors
    if (res.status >= 500) {
      const msg = json.error?.message || `Server error (${res.status})`;
      if (!silent) emitToast(msg, 'error');
      return { data: null, error: msg, meta: null };
    }

    return {
      data: json.data ?? null,
      error: json.error?.message ?? json.error ?? (res.ok ? null : `HTTP ${res.status}`),
      meta: json.meta ?? null,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Network error';
    if (!silent) emitToast(`Connection failed: ${msg}`, 'error');
    return { data: null, error: msg, meta: null };
  }
}

export { API_URL };
