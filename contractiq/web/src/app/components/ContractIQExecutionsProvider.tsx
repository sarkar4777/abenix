'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode } from 'react';

export interface ActiveExecution {
  executionId: string;
  agentSlug?: string;
  startedAt: number;
  title?: string;
  pageId?: string;
}

export interface ExecNotification {
  id: string;
  executionId: string;
  agentSlug?: string;
  title: string;
  status: 'completed' | 'failed' | 'timeout';
  finishedAt: number;
  read: boolean;
  href: string;
}

interface ContextValue {
  active: ActiveExecution[];
  notifications: ExecNotification[];
  unreadCount: number;
  registerExecution: (exec: Omit<ActiveExecution, 'startedAt'> & { startedAt?: number }) => void;
  clearExecution: (executionId: string) => void;
  markNotificationRead: (id: string) => void;
  clearAllNotifications: () => void;
  selectExecutionForDrawer: (executionId: string | null) => void;
  drawerExecutionId: string | null;
}

const Ctx = createContext<ContextValue | null>(null);

const TERMINAL = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);
const POLL_INTERVAL_MS = 5000;
const NOTIFICATION_CAP = 30;
const ACTIVE_KEY = 'contractiq:active-executions';
const NOTIF_KEY = 'contractiq:notifications';

function loadJSON<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function saveJSON(key: string, value: unknown) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch {}
}

export function ContractIQExecutionsProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<ActiveExecution[]>([]);
  const [notifications, setNotifications] = useState<ExecNotification[]>([]);
  const [drawerExecutionId, setDrawerExecutionId] = useState<string | null>(null);
  const pollersRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  const inFlightRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    setActive(loadJSON<ActiveExecution[]>(ACTIVE_KEY, []));
    setNotifications(loadJSON<ExecNotification[]>(NOTIF_KEY, []));
  }, []);

  useEffect(() => { saveJSON(ACTIVE_KEY, active); }, [active]);
  useEffect(() => { saveJSON(NOTIF_KEY, notifications); }, [notifications]);

  const finishExecution = useCallback((exec: ActiveExecution, status: 'completed' | 'failed' | 'timeout') => {
    setActive((prev) => prev.filter((e) => e.executionId !== exec.executionId));
    const notif: ExecNotification = {
      id: `${exec.executionId}-${Date.now()}`,
      executionId: exec.executionId,
      agentSlug: exec.agentSlug,
      title: exec.title || exec.agentSlug || 'execution',
      status, finishedAt: Date.now(), read: false,
      href: typeof window !== 'undefined' ? window.location.pathname : '/',
    };
    setNotifications((prev) => [notif, ...prev].slice(0, NOTIFICATION_CAP));
  }, []);

  const pollOne = useCallback(async (exec: ActiveExecution) => {
    if (inFlightRef.current.has(exec.executionId)) return;
    inFlightRef.current.add(exec.executionId);
    try {
      const r = await fetch(`/api/contractiq-executions/${exec.executionId}`, { cache: 'no-store' });
      if (!r.ok) return;
      const j = await r.json();
      const data = j?.data || {};
      const status = String(data?.status || '').toLowerCase();
      if (TERMINAL.has(status)) {
        const mapped: 'completed' | 'failed' | 'timeout' =
          status === 'completed' || status === 'succeeded' ? 'completed' :
          status === 'failed' || status === 'error' ? 'failed' : 'timeout';
        finishExecution(exec, mapped);
      } else if (Date.now() - exec.startedAt > 15 * 60 * 1000) {
        finishExecution(exec, 'timeout');
      }
    } catch {} finally {
      inFlightRef.current.delete(exec.executionId);
    }
  }, [finishExecution]);

  useEffect(() => {
    const current = pollersRef.current;
    const activeIds = new Set(active.map((e) => e.executionId));
    for (const [id, timer] of current.entries()) {
      if (!activeIds.has(id)) { clearInterval(timer); current.delete(id); }
    }
    for (const exec of active) {
      if (!current.has(exec.executionId)) {
        pollOne(exec);
        const t = setInterval(() => pollOne(exec), POLL_INTERVAL_MS);
        current.set(exec.executionId, t);
      }
    }
  }, [active, pollOne]);

  useEffect(() => () => {
    for (const t of pollersRef.current.values()) clearInterval(t);
    pollersRef.current.clear();
  }, []);

  const registerExecution = useCallback((exec: Omit<ActiveExecution, 'startedAt'> & { startedAt?: number }) => {
    setActive((prev) => {
      if (prev.some((e) => e.executionId === exec.executionId)) return prev;
      return [...prev, { startedAt: Date.now(), ...exec }];
    });
  }, []);

  const clearExecution = useCallback((executionId: string) => {
    setActive((prev) => prev.filter((e) => e.executionId !== executionId));
  }, []);

  const markNotificationRead = useCallback((id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  }, []);

  const clearAllNotifications = useCallback(() => setNotifications([]), []);

  const selectExecutionForDrawer = useCallback((id: string | null) => setDrawerExecutionId(id), []);

  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications]);

  return (
    <Ctx.Provider value={{
      active, notifications, unreadCount,
      registerExecution, clearExecution,
      markNotificationRead, clearAllNotifications,
      selectExecutionForDrawer, drawerExecutionId,
    }}>
      {children}
    </Ctx.Provider>
  );
}

export function useContractIQExecutions(): ContextValue {
  const v = useContext(Ctx);
  if (!v) {
    return {
      active: [], notifications: [], unreadCount: 0,
      registerExecution: () => {}, clearExecution: () => {},
      markNotificationRead: () => {}, clearAllNotifications: () => {},
      selectExecutionForDrawer: () => {}, drawerExecutionId: null,
    };
  }
  return v;
}
