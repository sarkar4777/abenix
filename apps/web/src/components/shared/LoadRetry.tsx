'use client';

import { RefreshCw } from 'lucide-react';

// honest stand-in for data that failed to load, never a false empty or offline state
export default function LoadRetry({
  what,
  onRetry,
  testId = 'load-retry',
  compact = false,
}: {
  what: string;
  onRetry?: () => void;
  testId?: string;
  compact?: boolean;
}) {
  return (
    <div
      role="status"
      data-testid={testId}
      className={`flex flex-wrap items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 text-amber-100 ${compact ? 'px-2.5 py-1.5 text-xs' : 'mb-4 px-3 py-2 text-sm'}`}
    >
      <RefreshCw className="h-3.5 w-3.5 shrink-0 animate-spin text-amber-300" aria-hidden />
      <span className="min-w-0">Couldn&apos;t load {what}, retrying.</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-amber-500/40 px-2 py-0.5 text-xs font-medium text-amber-100 hover:bg-amber-500/10"
        >
          Retry
        </button>
      )}
    </div>
  );
}
