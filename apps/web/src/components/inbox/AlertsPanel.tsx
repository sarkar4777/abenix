'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle2, Loader2, TrendingUp } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { failureLabel } from '@/lib/monitor-format';
import { relTime } from '@/lib/autonomy';

interface Rising {
  failure_code: string;
  count: number;
  previous: number;
  trend: 'new' | 'rising';
  latest_at: string | null;
}

// failure causes that are new today or up on yesterday, the Alerts page has the detail
export default function AlertsPanel({ onCount }: { onCount?: (n: number) => void }) {
  const { data, error, isLoading, mutate } = useApi<Rising[]>('/api/me/inbox/alerts', { refreshInterval: 60_000 });
  const groups = data || [];

  useEffect(() => {
    if (data) onCount?.(data.length);
  }, [data, onCount]);

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading alerts
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
        <AlertTriangle className="h-4 w-4" /> Alerts could not be loaded.
        <button type="button" onClick={mutate} className="ml-auto text-xs underline">Try again</button>
      </div>
    );
  }
  if (groups.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-700/50 bg-slate-800/20 p-8 text-center" data-testid="inbox-alerts-empty">
        <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-400/40" />
        <p className="text-sm text-slate-400">No failure is new or rising. When one starts happening more often it shows here.</p>
      </div>
    );
  }
  return (
    <ul className="space-y-3" data-testid="inbox-alerts">
      {groups.map((g) => (
        <li key={g.failure_code} className="rounded-xl border border-slate-700/50 bg-slate-800/40 p-4" data-testid="inbox-alert">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <TrendingUp className="h-4 w-4 shrink-0 text-amber-400" />
                <h3 className="min-w-0 break-words text-sm font-semibold text-white">{failureLabel(g.failure_code) || 'Failed runs'}</h3>
                <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[10px] text-amber-300">
                  {g.trend === 'new' ? 'New today' : 'Rising'}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">
                {g.count} failed in the last 24 hours, {g.previous} the day before
                {g.latest_at ? `. Last one ${relTime(g.latest_at)}` : ''}
              </p>
            </div>
            <div className="flex w-full shrink-0 gap-2 sm:w-auto">
              <Link
                href="/executions?status=failed&since=today"
                className="flex flex-1 items-center justify-center rounded-lg border border-slate-600 px-3 py-2 text-xs text-slate-200 hover:bg-slate-800 sm:flex-none"
              >
                See failed runs
              </Link>
              <Link
                href="/alerts"
                className="flex flex-1 items-center justify-center rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-300 hover:bg-cyan-500/20 sm:flex-none"
              >
                What to do
              </Link>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
