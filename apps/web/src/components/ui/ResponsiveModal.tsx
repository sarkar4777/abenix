'use client';

import { useEffect, type ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import { useIsMobile } from '@/hooks/useMediaQuery';

interface ResponsiveModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  maxWidth?: string;
}

export default function ResponsiveModal({
  open,
  onClose,
  title,
  icon,
  children,
  maxWidth = 'max-w-lg',
}: ResponsiveModalProps) {
  const isMobile = useIsMobile();

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={isMobile ? undefined : onClose}
          />

          {/* Panel */}
          {isMobile ? (
            <motion.div
              className="relative z-10 flex h-full w-full flex-col bg-[#0F172A]"
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 30, stiffness: 300 }}
            >
              {/* Header */}
              <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-700/50 bg-[#0F172A] px-4 py-3">
                {icon && (
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-500">
                    {icon}
                  </span>
                )}
                <h2 className="flex-1 text-lg font-semibold text-slate-100">
                  {title}
                </h2>
                <button
                  onClick={onClose}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-4">{children}</div>
            </motion.div>
          ) : (
            <motion.div
              className={`relative z-10 mx-4 flex max-h-[90vh] w-full flex-col rounded-xl border border-slate-700/50 bg-[#0F172A] shadow-2xl ${maxWidth}`}
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.2 }}
            >
              {/* Header */}
              <div className="sticky top-0 z-20 flex items-center gap-3 rounded-t-xl border-b border-slate-700/50 bg-[#0F172A] px-6 py-4">
                {icon && (
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-500">
                    {icon}
                  </span>
                )}
                <h2 className="flex-1 text-lg font-semibold text-slate-100">
                  {title}
                </h2>
                <button
                  onClick={onClose}
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
                >
                  <X size={18} />
                </button>
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto p-6">{children}</div>
            </motion.div>
          )}
        </div>
      )}
    </AnimatePresence>
  );
}
