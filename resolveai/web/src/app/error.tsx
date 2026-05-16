'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { AlertTriangle, RefreshCw, Home } from 'lucide-react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('ResolveAI page error:', error);
  }, [error]);

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle className="w-6 h-6 text-rose-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-semibold text-white">Something on this page broke.</h2>
            <p className="text-sm text-slate-300 mt-1">
              The rest of ResolveAI is still working — your session, cases, and
              admin data are all safe. This one page just tripped.
            </p>
            {error.message && (
              <pre className="mt-3 p-3 bg-slate-900/60 border border-slate-700/40 rounded text-[11px] text-rose-200 font-mono whitespace-pre-wrap break-words">
                {error.message.slice(0, 600)}
              </pre>
            )}
            {error.digest && (
              <p className="mt-2 text-[10px] text-slate-500 font-mono">ref: {error.digest}</p>
            )}
            <div className="mt-4 flex items-center gap-2">
              <button
                onClick={reset}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-sm font-medium transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Retry this page
              </button>
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-800/30 hover:bg-slate-800/60 text-slate-200 text-sm transition-colors"
              >
                <Home className="w-3.5 h-3.5" /> Back to dashboard
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
