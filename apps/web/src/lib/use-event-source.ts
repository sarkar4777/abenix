'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

interface UseEventSourceOptions {
  url: string;
  onMessage: (data: string) => void;
  onError?: (error: Event) => void;
  enabled?: boolean;
  maxRetries?: number;
}

export function useEventSource({
  url,
  onMessage,
  onError,
  enabled = true,
  maxRetries = 10,
}: UseEventSourceOptions) {
  const [connected, setConnected] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const retriesRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!enabled) return;
    if (esRef.current) {
      esRef.current.close();
    }

    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
    const separator = url.includes('?') ? '&' : '?';
    const fullUrl = token ? `${url}${separator}token=${token}` : url;

    const es = new EventSource(fullUrl);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      retriesRef.current = 0;
      setRetryCount(0);
    };

    es.onmessage = (event) => {
      onMessage(event.data);
    };

    es.onerror = (event) => {
      setConnected(false);
      es.close();
      esRef.current = null;
      onError?.(event);

      if (retriesRef.current < maxRetries) {
        // Exponential backoff: 1s, 2s, 4s, 8s, ... max 30s
        const delay = Math.min(1000 * Math.pow(2, retriesRef.current), 30000);
        retriesRef.current++;
        setRetryCount(retriesRef.current);
        timeoutRef.current = setTimeout(connect, delay);
      }
    };
  }, [url, onMessage, onError, enabled, maxRetries]);

  useEffect(() => {
    connect();
    return () => {
      if (esRef.current) esRef.current.close();
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [connect]);

  const disconnect = useCallback(() => {
    if (esRef.current) esRef.current.close();
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    esRef.current = null;
    setConnected(false);
  }, []);

  return { connected, retryCount, disconnect };
}
