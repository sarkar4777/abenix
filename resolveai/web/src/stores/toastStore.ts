'use client';

/**
 * Tiny global toast store — no dependency on Zustand or similar to
 * keep the ResolveAI bundle small. Pages and helpers call
 * `toastError(msg)` / `toastSuccess(msg)`; the <ToastHost /> component
 * mounted in the root layout subscribes to changes and renders.
 */
import { useEffect, useState } from 'react';

export type ToastTone = 'success' | 'error' | 'info';

export interface ToastMessage {
  id: string;
  tone: ToastTone;
  text: string;
}

type Listener = (toasts: ToastMessage[]) => void;

let toasts: ToastMessage[] = [];
const listeners = new Set<Listener>();

function emit() {
  // Snapshot so React's setState picks up the change.
  const snapshot = toasts.slice();
  for (const l of listeners) l(snapshot);
}

function push(tone: ToastTone, text: string, ttlMs = 4000) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  toasts = [...toasts, { id, tone, text }];
  emit();
  if (ttlMs > 0) {
    setTimeout(() => dismiss(id), ttlMs);
  }
}

export function dismiss(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function toastSuccess(text: string) {
  push('success', text);
}

export function toastError(text: string) {
  push('error', text, 6000);
}

export function toastInfo(text: string) {
  push('info', text);
}

export function useToasts(): ToastMessage[] {
  const [state, setState] = useState<ToastMessage[]>(toasts);
  useEffect(() => {
    const listener: Listener = (next) => setState(next);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return state;
}
