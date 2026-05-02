'use client';

import { useToasts, dismissToast } from '@/stores/toastStore';
import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';

export default function ToastViewport() {
  const toasts = useToasts();
  if (!toasts.length) return null;
  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 w-[360px] max-w-[90vw]">
      {toasts.map(t => {
        const palette =
          t.kind === 'error'
            ? 'border-red-700/60 bg-red-950/85 text-red-100'
            : t.kind === 'success'
              ? 'border-green-600/60 bg-green-950/85 text-green-100'
              : 'border-green-800/60 bg-[#0A2818]/90 text-green-200';
        const Icon = t.kind === 'error' ? AlertCircle : t.kind === 'success' ? CheckCircle2 : Info;
        return (
          <div
            key={t.id}
            className={`rounded-xl border px-4 py-3 shadow-lg backdrop-blur-md flex items-start gap-3 ${palette}`}
            role="alert"
          >
            <Icon className="w-4 h-4 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium leading-snug">{t.message}</p>
              {t.detail && (
                <p className="text-[11px] opacity-70 mt-0.5 break-words">{t.detail}</p>
              )}
            </div>
            <button
              onClick={() => dismissToast(t.id)}
              className="opacity-50 hover:opacity-100 transition-opacity shrink-0"
              aria-label="Dismiss"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
