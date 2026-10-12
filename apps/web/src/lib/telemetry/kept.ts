'use client';

import { useCallback, useState } from 'react';

// state that outlives a remount, so a one-time key is not lost when a phone turns and the dialog redraws
const kept = new Map<string, unknown>();

export function useKept<T>(key: string, init: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => (kept.has(key) ? (kept.get(key) as T) : init));
  const set = useCallback((n: T) => {
    kept.set(key, n);
    setV(n);
  }, [key]);
  return [v, set];
}

export function forgetKept(prefix: string) {
  for (const k of Array.from(kept.keys())) if (k.startsWith(prefix)) kept.delete(k);
}
