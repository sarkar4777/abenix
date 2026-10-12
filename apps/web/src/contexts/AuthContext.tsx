'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { refreshSession, setApiConnection } from '@/lib/api-client';

interface User {
  id: string;
  email: string;
  full_name: string;
  avatar_url: string | null;
  role: string;
  tenant_id: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  reconnecting: boolean;
  retryNow: () => void;
  logout: () => void;
  updateUser: (patch: Partial<User>) => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  reconnecting: false,
  retryNow: () => {},
  logout: () => {},
  updateUser: () => {},
});

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const AUTH_BACKOFF_MS = [1000, 2000, 4000, 8000, 15000];
let backoff = AUTH_BACKOFF_MS;
export function setAuthBackoff(delays: number[]) {
  backoff = delays;
}

export type MeResult =
  | { kind: 'user'; user: User }
  | { kind: 'signed_out' }
  | { kind: 'unavailable' };

// one look at /me: a 401 tries a refresh, only a refused refresh signs the user out
export async function loadMe(): Promise<MeResult> {
  const token = localStorage.getItem('access_token');
  if (!token) return { kind: 'signed_out' };
  const call = async (t: string) => {
    try {
      return await fetch(`${API_URL}/api/auth/me`, { headers: { Authorization: `Bearer ${t}` } });
    } catch {
      return null;
    }
  };
  let res = await call(token);
  if (res && res.status === 401) {
    const r = await refreshSession();
    if (r.kind === 'invalid') return { kind: 'signed_out' };
    if (r.kind === 'unavailable') return { kind: 'unavailable' };
    res = await call(r.token);
    if (res && res.status === 401) return { kind: 'signed_out' };
  }
  if (res && res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
    return { kind: 'signed_out' };
  }
  if (!res || !res.ok) return { kind: 'unavailable' };
  try {
    const json = await res.json();
    if (json?.data?.user) return { kind: 'user', user: json.data.user };
  } catch {
    /* half a body is still a busy server */
  }
  return { kind: 'unavailable' };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);
  const attempt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  const check = useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const out = await loadMe();
    if (!alive.current) return;
    if (out.kind === 'user') {
      attempt.current = 0;
      setUser(out.user);
      setReconnecting(false);
      setApiConnection('ok');
      setLoading(false);
    } else if (out.kind === 'signed_out') {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      setUser(null);
      setReconnecting(false);
      setLoading(false);
    } else {
      setReconnecting(true);
      setApiConnection('reconnecting');
      const delay = backoff[Math.min(attempt.current, backoff.length - 1)];
      attempt.current += 1;
      timer.current = setTimeout(() => void check(), delay);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void check();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [check]);

  const retryNow = useCallback(() => {
    attempt.current = 0;
    void check();
  }, [check]);

  const logout = useCallback(async () => {
    const token = localStorage.getItem('access_token');
    if (token) {
      try {
        await fetch(`${API_URL}/api/auth/logout`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          keepalive: true,
        });
      } catch {}
    }
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setUser(null);
    window.location.href = '/';
  }, []);

  // lets settings pages push saved fields to the sidebar and status bar without a reload
  const updateUser = useCallback((patch: Partial<User>) => {
    setUser((u) => (u ? { ...u, ...patch } : u));
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, reconnecting, retryNow, logout, updateUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
