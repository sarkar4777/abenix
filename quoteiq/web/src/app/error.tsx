'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react';

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('QuoteIQ page error:', error);
  }, [error]);

  return (
    <main className="p-8 max-w-3xl mx-auto">
      <div className="rounded-xl ring-1 ring-rose-500/30 bg-rose-500/5 p-6 flex items-start gap-3">
        <AlertTriangle className="w-6 h-6 text-rose-400 shrink-0 mt-0.5" />
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-white">This page broke.</h2>
          <p className="text-sm text-slate-300 mt-1">
            The emails and their reviews are kept by the QuoteIQ API, so nothing is lost.
          </p>
          {error.message && <pre className="mt-3 text-xs text-rose-200/80 whitespace-pre-wrap">{error.message}</pre>}
          <div className="flex gap-2 mt-4">
            <button onClick={reset} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 text-sm font-medium">
              <RefreshCw className="w-3.5 h-3.5" /> Try again
            </button>
            <Link href="/" className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg ring-1 ring-slate-700 text-sm text-slate-200 hover:bg-slate-800">
              <Inbox className="w-3.5 h-3.5" /> Inbox
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
