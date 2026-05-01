import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number;
}

interface ToastState {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
}

const MAX_TOASTS = 5;
const DEFAULT_DURATION = 5000;

const dismissTimers = new Map<string, ReturnType<typeof setTimeout>>();

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  addToast: (toast) => {
    const id =
      Date.now().toString(36) + Math.random().toString(36).substring(2, 8);
    const duration = toast.duration ?? DEFAULT_DURATION;
    const newToast: Toast = { ...toast, id, duration };

    set((state) => {
      let next = [...state.toasts, newToast];

      // Enforce max visible toasts — remove oldest when exceeding limit
      while (next.length > MAX_TOASTS) {
        const removed = next.shift();
        if (removed) {
          const timer = dismissTimers.get(removed.id);
          if (timer) {
            clearTimeout(timer);
            dismissTimers.delete(removed.id);
          }
        }
      }

      return { toasts: next };
    });

    // Auto-dismiss after duration
    if (duration > 0) {
      const timer = setTimeout(() => {
        get().removeToast(id);
      }, duration);
      dismissTimers.set(id, timer);
    }
  },

  removeToast: (id) => {
    const timer = dismissTimers.get(id);
    if (timer) {
      clearTimeout(timer);
      dismissTimers.delete(id);
    }

    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },
}));

// ── Convenience functions ──────────────────────────────────────────────

export function toast(opts: Omit<Toast, 'id'>): void {
  useToastStore.getState().addToast(opts);
}

export function toastSuccess(title: string, message?: string): void {
  useToastStore.getState().addToast({ type: 'success', title, message });
}

export function toastError(title: string, message?: string): void {
  useToastStore.getState().addToast({ type: 'error', title, message });
}

export function toastWarning(title: string, message?: string): void {
  useToastStore.getState().addToast({ type: 'warning', title, message });
}

export function toastInfo(title: string, message?: string): void {
  useToastStore.getState().addToast({ type: 'info', title, message });
}
