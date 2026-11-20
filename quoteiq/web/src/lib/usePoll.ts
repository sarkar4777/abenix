'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { REFRESH_EVENT, type Result } from './api';

/** How often the pages reload what they show. */
export const POLL_MS = 5000;

/**
 * Load a resource and keep it fresh. Runs move over seconds to minutes, so
 * pages poll rather than make the reviewer reload; any action can ask for an
 * immediate reload with refreshAll().
 */
export function usePoll<T>(load: () => Promise<Result<T>>, intervalMs: number, key: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState(0);
  const inflight = useRef(false);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(async () => {
    if (inflight.current) return;
    inflight.current = true;
    try {
      const res = await loadRef.current();
      setStatus(res.status);
      if (res.error) {
        setError(res.error);
      } else {
        setData(res.data);
        setError(null);
      }
    } finally {
      inflight.current = false;
    }
  }, []);

  useEffect(() => {
    setData(null);
    setError(null);
    void reload();
  }, [key, reload]);

  useEffect(() => {
    const timer = setInterval(() => void reload(), intervalMs);
    const onRefresh = () => void reload();
    window.addEventListener(REFRESH_EVENT, onRefresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener(REFRESH_EVENT, onRefresh);
    };
  }, [intervalMs, reload]);

  return { data, error, status, reload, setData };
}
