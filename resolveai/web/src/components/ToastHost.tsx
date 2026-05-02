'use client';

/**
 * Renders the live toast stack. Mounted once in the root layout so
 * any client page can call `toastError` / `toastSuccess` and have it
 * surface without prop-drilling.
 */
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';
import { dismiss, useToasts } from '@/stores/toastStore';

const TONE_STYLES: Record<string, { ring: string; icon: JSX.Element; bg: string }> = {
  success: {
    ring: 'border-emerald-500/40',
    bg: 'bg-emerald-500/10 text-emerald-100',
    icon: <CheckCircle2 className="w-4 h-4 text-emerald-300" />,
  },
  error: {
    ring: 'border-rose-500/40',
    bg: 'bg-rose-500/10 text-rose-100',
    icon: <AlertCircle className="w-4 h-4 text-rose-300" />,
  },
  info: {
    ring: 'border-cyan-500/40',
    bg: 'bg-cyan-500/10 text-cyan-100',
    icon: <Info className="w-4 h-4 text-cyan-300" />,
  },
};

export default function ToastHost() {
  const toasts = useToasts();
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none" data-testid="toast-host">
      {toasts.map((t) => {
        const style = TONE_STYLES[t.tone] ?? TONE_STYLES.info;
        return (
          <div
            key={t.id}
            data-testid={`toast-${t.tone}`}
            className={`pointer-events-auto flex items-start gap-2 max-w-sm rounded-lg border ${style.ring} ${style.bg} px-3 py-2 text-xs shadow-lg`}
          >
            <span className="shrink-0 mt-0.5">{style.icon}</span>
            <span className="flex-1">{t.text}</span>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 text-slate-400 hover:text-white"
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
