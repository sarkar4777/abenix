'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode } from 'react';

export type WingmanPageId =
  | 'desk' | 'arbitrage' | 'mispricing' | 'scenarios' | 'graph' | 'operations';

export interface WingmanActiveExecution {
  pageId: WingmanPageId;
  executionId: string;
  agentSlug?: string;
  startedAt: number;
  title?: string;
  subjectId?: string;
}

export interface WingmanNotification {
  id: string;
  pageId: WingmanPageId;
  executionId: string;
  agentSlug?: string;
  title: string;
  status: 'completed' | 'failed' | 'timeout';
  finishedAt: number;
  read: boolean;
  href: string;
}

interface ContextValue {
  active: WingmanActiveExecution[];
  notifications: WingmanNotification[];
  unreadCount: number;
  registerExecution: (exec: Omit<WingmanActiveExecution, 'startedAt'> & { startedAt?: number }) => void;
  clearExecution: (executionId: string) => void;
  getActiveForPage: (pageId: WingmanPageId) => WingmanActiveExecution[];
  markNotificationRead: (id: string) => void;
  clearAllNotifications: () => void;
}

const Ctx = createContext<ContextValue | null>(null);

const TERMINAL = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);
const POLL_INTERVAL_MS = 5000;
const NOTIFICATION_CAP = 30;
const ACTIVE_KEY = 'wingman:active-executions';
const NOTIF_KEY = 'wingman:notifications';

const PAGE_RESULT_PATH: Record<WingmanPageId, string> = {
  desk: '/api/wingman/desk/result',
  arbitrage: '/api/wingman/analyze-result',
  mispricing: '/api/wingman/mispricing-result',
  scenarios: '/api/wingman/scenario-result',
  graph: '/api/wingman/executions',
  operations: '/api/wingman/executions',
};

const PAGE_HREF: Record<WingmanPageId, string> = {
  desk: '/desk',
  arbitrage: '/workbench',
  mispricing: '/mispricing',
  scenarios: '/scenarios',
  graph: '/graph',
  operations: '/ops',
};

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
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota / serialization — ignore
  }
}

export function WingmanExecutionsProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<WingmanActiveExecution[]>([]);
  const [notifications, setNotifications] = useState<WingmanNotification[]>([]);
  const pollersRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  const inFlightStatusRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    setActive(loadJSON<WingmanActiveExecution[]>(ACTIVE_KEY, []));
    setNotifications(loadJSON<WingmanNotification[]>(NOTIF_KEY, []));
  }, []);

  useEffect(() => { saveJSON(ACTIVE_KEY, active); }, [active]);
  useEffect(() => { saveJSON(NOTIF_KEY, notifications); }, [notifications]);

  const finishExecution = useCallback((exec: WingmanActiveExecution, status: 'completed' | 'failed' | 'timeout') => {
    setActive((prev) => prev.filter((e) => e.executionId !== exec.executionId));
    const notif: WingmanNotification = {
      id: `${exec.executionId}-${Date.now()}`,
      pageId: exec.pageId,
      executionId: exec.executionId,
      agentSlug: exec.agentSlug,
      title: exec.title || exec.agentSlug || exec.pageId,
      status,
      finishedAt: Date.now(),
      read: false,
      href: `${PAGE_HREF[exec.pageId]}?exec=${exec.executionId}`,
    };
    setNotifications((prev) => [notif, ...prev].slice(0, NOTIFICATION_CAP));
  }, []);

  const pollOne = useCallback(async (exec: WingmanActiveExecution) => {
    if (inFlightStatusRef.current.has(exec.executionId)) return;
    inFlightStatusRef.current.add(exec.executionId);
    try {
      const path = PAGE_RESULT_PATH[exec.pageId];
      const url = exec.pageId === 'arbitrage'
        ? `${path}/${exec.executionId}`
        : `${path}/${exec.executionId}`;
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) return;
      const j = await r.json();
      const data = j?.data || {};
      const status = String(data?.status || '').toLowerCase();
      if (TERMINAL.has(status)) {
        const mapped: 'completed' | 'failed' | 'timeout' =
          status === 'completed' || status === 'succeeded' ? 'completed' :
          status === 'failed' || status === 'error' ? 'failed' :
          'timeout';
        finishExecution(exec, mapped);
      } else if (Date.now() - exec.startedAt > 15 * 60 * 1000) {
        finishExecution(exec, 'timeout');
      }
    } catch {
      // network blip; keep polling
    } finally {
      inFlightStatusRef.current.delete(exec.executionId);
    }
  }, [finishExecution]);

  useEffect(() => {
    const current = pollersRef.current;
    const activeIds = new Set(active.map((e) => e.executionId));
    for (const [id, timer] of current.entries()) {
      if (!activeIds.has(id)) {
        clearInterval(timer);
        current.delete(id);
      }
    }
    for (const exec of active) {
      if (!current.has(exec.executionId)) {
        pollOne(exec);
        const t = setInterval(() => pollOne(exec), POLL_INTERVAL_MS);
        current.set(exec.executionId, t);
      }
    }
    return () => { /* cleanup happens on next effect run */ };
  }, [active, pollOne]);

  useEffect(() => {
    return () => {
      for (const t of pollersRef.current.values()) clearInterval(t);
      pollersRef.current.clear();
    };
  }, []);

  const registerExecution = useCallback((exec: Omit<WingmanActiveExecution, 'startedAt'> & { startedAt?: number }) => {
    setActive((prev) => {
      if (prev.some((e) => e.executionId === exec.executionId)) return prev;
      return [...prev, { startedAt: Date.now(), ...exec }];
    });
  }, []);

  const clearExecution = useCallback((executionId: string) => {
    setActive((prev) => prev.filter((e) => e.executionId !== executionId));
  }, []);

  const getActiveForPage = useCallback((pageId: WingmanPageId) => {
    return active.filter((e) => e.pageId === pageId);
  }, [active]);

  const markNotificationRead = useCallback((id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
  }, []);

  const clearAllNotifications = useCallback(() => {
    setNotifications([]);
  }, []);

  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications]);

  const value: ContextValue = {
    active,
    notifications,
    unreadCount,
    registerExecution,
    clearExecution,
    getActiveForPage,
    markNotificationRead,
    clearAllNotifications,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWingmanExecutions(): ContextValue {
  const v = useContext(Ctx);
  if (!v) {
    return {
      active: [], notifications: [], unreadCount: 0,
      registerExecution: () => {}, clearExecution: () => {},
      getActiveForPage: () => [],
      markNotificationRead: () => {}, clearAllNotifications: () => {},
    };
  }
  return v;
}

export function useWingmanPageExecution(pageId: WingmanPageId) {
  const { active, registerExecution, clearExecution, notifications } = useWingmanExecutions();
  const pageActive = useMemo(() => active.filter((e) => e.pageId === pageId), [active, pageId]);
  const pageCompletions = useMemo(() => notifications.filter((n) => n.pageId === pageId), [notifications, pageId]);
  return { pageActive, pageCompletions, registerExecution, clearExecution };
}
