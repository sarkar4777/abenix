'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[Abenix] Unhandled error:', error);
  }, [error]);

  const displayMessage =
    error.message && error.message.length > 200
      ? error.message.slice(0, 200) + '...'
      : error.message;

  return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center" role="alert">
      <div className="max-w-md text-center px-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
          className="w-16 h-16 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto"
        >
          <AlertTriangle className="w-8 h-8 text-red-400" aria-hidden="true" />
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1, duration: 0.4 }}
          className="text-xl font-semibold text-white mt-6"
        >
          Something went wrong
        </motion.h1>

        {displayMessage && (
          <motion.p
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.4 }}
            className="text-sm text-slate-400 mt-2 break-words"
          >
            {displayMessage}
          </motion.p>
        )}

        {error.digest && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.25, duration: 0.4 }}
            className="text-xs text-slate-500 mt-1 font-mono"
          >
            Error ID: {error.digest}
          </motion.p>
        )}

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.4 }}
          className="mt-8 flex items-center gap-3 justify-center"
        >
          <button
            onClick={reset}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-semibold shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 hover:-translate-y-0.5 transition-all duration-200"
            aria-label="Try again to reload the page"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
            Try Again
          </button>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-slate-700/50 border border-slate-600 text-slate-300 text-sm font-semibold hover:bg-slate-700 hover:text-white hover:-translate-y-0.5 transition-all duration-200"
            aria-label="Go to the dashboard home page"
          >
            <Home className="w-4 h-4" aria-hidden="true" />
            Go Home
          </Link>
        </motion.div>
      </div>
    </div>
  );
}
