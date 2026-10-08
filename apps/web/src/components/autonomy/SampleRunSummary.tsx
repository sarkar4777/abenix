'use client';

import Link from 'next/link';
import { ArrowDown, CheckCircle2, RefreshCw } from 'lucide-react';
import { runSummaryText, type RunSummary } from '@/lib/autonomy';

interface Props {
  summary: RunSummary;
  canRun: boolean;
  runBusy: boolean;
  onRunAgain: () => void;
  onReview: (status: 'watching' | 'pending') => void;
}

export default function SampleRunSummary({ summary, canRun, runBusy, onRunAgain, onReview }: Props) {
  const s = summary;
  const waitWord = s.reviewStatus === 'watching' ? 'waiting for your review' : 'waiting for approval';
  return (
    <div className="mt-2 rounded-lg border border-violet-500/30 bg-slate-900/40 p-3 text-xs text-violet-100" data-testid="autonomy-run-summary" aria-live="polite">
      <p className="flex items-start gap-2">
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet-300" />
        <span>{runSummaryText(s)}</span>
      </p>
      {s.failed.length > 0 && (
        <p className="mt-1.5 text-rose-300" data-testid="autonomy-run-failed">
          {s.failed.length} run{s.failed.length === 1 ? '' : 's'} failed:{' '}
          {s.failed.map((id, i) => (
            <span key={id}>
              {i > 0 && ', '}
              <Link href={`/executions/${id}`} className="font-mono underline">{id.slice(0, 8)}</Link>
            </span>
          ))}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {s.reviewStatus && s.reviewCount > 0 && (
          <>
            <span>{s.reviewCount} {waitWord}.</span>
            <button
              type="button"
              onClick={() => onReview(s.reviewStatus!)}
              className="inline-flex items-center gap-1 rounded-md bg-violet-500/30 px-2.5 py-1 font-medium text-white hover:bg-violet-500/50"
              data-testid="autonomy-timeline-review"
            >
              <ArrowDown className="h-3 w-3" /> Review them here
            </button>
          </>
        )}
        {s.newActions === 0 && (
          <button
            type="button"
            disabled={!canRun || runBusy}
            title={canRun ? undefined : 'Needs the autonomy.manage permission'}
            onClick={onRunAgain}
            className="inline-flex items-center gap-1 rounded-md border border-violet-400/40 px-2.5 py-1 font-medium text-violet-100 hover:bg-violet-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="autonomy-run-again"
          >
            <RefreshCw className="h-3 w-3" /> Run again
          </button>
        )}
      </div>
    </div>
  );
}
