'use client';

import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  X,
} from 'lucide-react';
import { useToastStore, type ToastType, type Toast } from '@/stores/toastStore';

const iconMap: Record<ToastType, React.ElementType> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const iconColorMap: Record<ToastType, string> = {
  success: 'text-emerald-400',
  error: 'text-red-400',
  warning: 'text-amber-400',
  info: 'text-blue-400',
};

const accentColorMap: Record<ToastType, string> = {
  success: 'bg-emerald-500',
  error: 'bg-red-500',
  warning: 'bg-amber-500',
  info: 'bg-blue-500',
};

const progressColorMap: Record<ToastType, string> = {
  success: 'bg-emerald-500/60',
  error: 'bg-red-500/60',
  warning: 'bg-amber-500/60',
  info: 'bg-blue-500/60',
};

function ToastCard({ toast }: { toast: Toast }) {
  const removeToast = useToastStore((s) => s.removeToast);
  const progressRef = useRef<HTMLDivElement>(null);
  const Icon = iconMap[toast.type];
  const duration = toast.duration ?? 5000;

  useEffect(() => {
    const bar = progressRef.current;
    if (!bar || duration <= 0) return;

    // Force reflow so the animation starts from full width
    bar.style.transition = 'none';
    bar.style.width = '100%';
    bar.getBoundingClientRect();

    bar.style.transition = `width ${duration}ms linear`;
    bar.style.width = '0%';
  }, [duration]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 100, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100, scale: 0.95 }}
      transition={{ type: 'spring', damping: 25, stiffness: 300 }}
      className="pointer-events-auto relative flex w-full overflow-hidden rounded-xl border border-slate-700/50 bg-slate-800/90 shadow-2xl shadow-black/50 backdrop-blur-xl"
    >
      {/* Left accent bar */}
      <div className={`w-1 shrink-0 ${accentColorMap[toast.type]}`} />

      {/* Content area */}
      <div className="flex min-w-0 flex-1 items-start gap-3 px-3 py-3">
        {/* Icon */}
        <div className={`mt-0.5 shrink-0 ${iconColorMap[toast.type]}`}>
          <Icon size={18} />
        </div>

        {/* Text */}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-white">{toast.title}</p>
          {toast.message && (
            <p className="mt-0.5 text-xs text-slate-400">{toast.message}</p>
          )}
        </div>

        {/* Close button */}
        <button
          onClick={() => removeToast(toast.id)}
          className="shrink-0 rounded-md p-0.5 text-slate-500 transition-colors hover:text-white"
          aria-label="Dismiss notification"
        >
          <X size={14} />
        </button>
      </div>

      {/* Progress bar */}
      {duration > 0 && (
        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-slate-700/30">
          <div
            ref={progressRef}
            className={`h-full ${progressColorMap[toast.type]}`}
          />
        </div>
      )}
    </motion.div>
  );
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);

  return (
    <div className="pointer-events-none fixed right-4 top-4 z-[100] flex w-80 flex-col gap-2">
      <AnimatePresence mode="popLayout">
        {toasts.map((t) => (
          <ToastCard key={t.id} toast={t} />
        ))}
      </AnimatePresence>
    </div>
  );
}
