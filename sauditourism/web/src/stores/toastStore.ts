'use client';

/**
 * Tiny dependency-free toast store.
 *
 * Usage:
 *   import { toastError, toastSuccess } from '@/stores/toastStore';
 *   toastError('Failed to load reports', 500);
 *
 * Mount <ToastViewport/> once at the layout root.
 */

import { useEffect, useState } from 'react';

export type ToastKind = 'error' | 'success' | 'info';
export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  detail?: string;
}

type Listener = (toasts: Toast[]) => void;

let _toasts: Toast[] = [];
let _seq = 1;
const _listeners = new Set<Listener>();

function _emit() {
  for (const l of _listeners) l(_toasts.slice());
}

export function pushToast(kind: ToastKind, message: string, detail?: string, ttlMs = 6000) {
  const id = _seq++;
  const t: Toast = { id, kind, message, detail };
  _toasts = [..._toasts, t];
  _emit();
  if (ttlMs > 0) {
    setTimeout(() => dismissToast(id), ttlMs);
  }
  return id;
}

export function dismissToast(id: number) {
  _toasts = _toasts.filter(t => t.id !== id);
  _emit();
}

export function toastError(message: string, statusOrDetail?: number | string) {
  const detail =
    typeof statusOrDetail === 'number' ? `HTTP ${statusOrDetail}` : statusOrDetail || undefined;
  return pushToast('error', message, detail, 8000);
}

export function toastSuccess(message: string, detail?: string) {
  return pushToast('success', message, detail, 4000);
}

export function toastInfo(message: string, detail?: string) {
  return pushToast('info', message, detail, 4000);
}

export function useToasts(): Toast[] {
  const [list, setList] = useState<Toast[]>(_toasts);
  useEffect(() => {
    _listeners.add(setList);
    setList(_toasts.slice());
    return () => {
      _listeners.delete(setList);
    };
  }, []);
  return list;
}

/**
 * Wraps fetch and surfaces non-2xx responses as toasts.
 * Returns parsed JSON {data, error} or {data:null, error:{message}} on failure.
 */
export async function fetchWithToast(
  url: string,
  opts?: RequestInit & { signal?: AbortSignal },
  errorLabel = 'Request failed',
): Promise<any> {
  try {
    const res = await fetch(url, {
      ...opts,
      signal: opts?.signal ?? AbortSignal.timeout(600000),
    });
    const text = await res.text();
    let parsed: any = null;
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = { data: null, error: { message: text.slice(0, 200) } };
    }
    if (!res.ok) {
      const msg = parsed?.error?.message || parsed?.detail || `${errorLabel} (HTTP ${res.status})`;
      toastError(errorLabel, msg);
      return parsed ?? { data: null, error: { message: msg } };
    }
    return parsed;
  } catch (e: any) {
    const msg = e?.name === 'AbortError' ? 'Request timed out' : e?.message || String(e);
    toastError(errorLabel, msg);
    return { data: null, error: { message: msg } };
  }
}
