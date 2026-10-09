'use client';

import { useEffect, useState } from 'react';
import { Gauge } from 'lucide-react';
import { budgetNote, meterTone, proposalsApi, type Budget } from '@/lib/improvement-proposals';

function Meter({ label, used, limit, testid }: { label: string; used: number; limit: number; testid: string }) {
  const f = limit ? Math.min(1, used / limit) : 1;
  return (
    <div className="min-w-[110px]" data-testid={testid}>
      <div className="flex justify-between gap-2 text-[10px] text-slate-400">
        <span>{label}</span>
        <span className="text-slate-300">
          {used.toLocaleString()} of {limit.toLocaleString()}
        </span>
      </div>
      <div className="mt-0.5 h-1 rounded bg-slate-800" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={limit} aria-valuenow={used}>
        <div className={`h-1 rounded ${meterTone(used, limit)}`} style={{ width: `${f * 100}%` }} />
      </div>
    </div>
  );
}

export default function BudgetMeter() {
  const [b, setB] = useState<Budget | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const r = await proposalsApi.budget();
      if (!alive) return;
      if (r.error || !r.data) setErr(r.status === 404 ? 'Budget not available yet' : 'Budget could not be loaded');
      else {
        setErr(null);
        setB(r.data);
      }
    };
    load();
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  if (err) return <span className="text-[11px] text-slate-500" data-testid="budget-meter-error">{err}</span>;
  if (!b) return <span className="h-8 w-40 animate-pulse rounded-md bg-slate-800/60" data-testid="budget-meter-loading" aria-label="Loading the budget" />;
  const note = budgetNote(b);
  return (
    <div
      className="flex min-w-0 max-w-full flex-wrap items-center gap-3 rounded-md border border-slate-700/60 bg-slate-900/40 px-2.5 py-1.5"
      data-testid="budget-meter"
      title="Today's budget for proving fixes. When it is spent, proposals wait in line until tomorrow."
    >
      <Gauge className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
      <Meter label="Proofs today" used={b.proofs_today} limit={b.proofs_limit} testid="budget-proofs" />
      <Meter label="Tokens today" used={b.tokens_today} limit={b.tokens_limit} testid="budget-tokens" />
      <span className="text-[10px] text-slate-400" data-testid="budget-queue">
        {b.queue_depth ? `${b.queue_depth} in line` : 'Nothing in line'}
      </span>
      {b.stopped ? (
        <span className="basis-full text-[10px] text-rose-300" data-testid="budget-stopped">{b.stopped}</span>
      ) : (
        note && (
          <span className={`basis-full text-[10px] ${note.tone === 'spent' ? 'text-amber-300' : 'text-slate-400'}`} data-testid="budget-note" data-tone={note.tone}>
            {note.text}
          </span>
        )
      )}
    </div>
  );
}
