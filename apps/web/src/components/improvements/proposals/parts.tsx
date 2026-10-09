'use client';

import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';
import {
  MIN_SPEED_RUNS, STATE_TONE, money, pct, seconds, stepText, wordDiff,
  type DiffLine, type Example, type Proof, type ProofStep, type Proposal, type Scores,
} from '@/lib/improvement-proposals';

export function StateChip({ p }: { p: Pick<Proposal, 'state' | 'state_label'> }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] tracking-wide ${STATE_TONE[p.state]}`}
      data-testid="proposal-state"
      data-state={p.state}
    >
      {p.state_label}
    </span>
  );
}

export function ProofSteps({ steps, message }: { steps: ProofStep[]; message?: string }) {
  if (!steps.length) return null;
  return (
    <div data-testid="proof-steps">
      <ol className="flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:gap-4">
        {steps.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5 text-xs" data-testid={`proof-step-${s.key}`} data-step-state={s.state}>
            {s.state === 'done' ? (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" aria-hidden />
            ) : s.state === 'running' ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-300" aria-hidden />
            ) : s.state === 'failed' ? (
              <XCircle className="h-3.5 w-3.5 text-rose-400" aria-hidden />
            ) : (
              <Circle className="h-3.5 w-3.5 text-slate-600" aria-hidden />
            )}
            <span className={s.state === 'pending' ? 'text-slate-500' : 'text-slate-200'}>{stepText(s)}</span>
          </li>
        ))}
      </ol>
      {message && <p className="mt-1.5 text-[11px] text-slate-400" data-testid="proof-message">{message}</p>}
    </div>
  );
}

export function DiffView({ lines, what }: { lines: DiffLine[]; what?: string }) {
  const [shown, hidden] = trimSame(lines);
  if (!lines.length) return <p className="text-xs text-slate-500">No change drafted yet.</p>;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/60" data-testid="proposal-diff">
      {what && <p className="border-b border-slate-800 px-3 py-1.5 text-[10px] uppercase tracking-wider text-slate-500">Changes the {what}</p>}
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] leading-relaxed">
        {shown.map((l, i) => (
          <div
            key={i}
            className={
              l.op === 'add'
                ? 'bg-emerald-500/10 text-emerald-200'
                : l.op === 'remove'
                  ? 'bg-rose-500/10 text-rose-200 line-through decoration-rose-400/60'
                  : 'text-slate-400'
            }
          >
            <span className="select-none pr-2 text-slate-600">{l.op === 'add' ? '+' : l.op === 'remove' ? '-' : ' '}</span>
            {l.text || ' '}
          </div>
        ))}
        {hidden > 0 && <div className="text-slate-600">{hidden} unchanged lines hidden</div>}
      </pre>
    </div>
  );
}

// keep two lines of context around each change
function trimSame(lines: DiffLine[]): [DiffLine[], number] {
  const keep = new Set<number>();
  lines.forEach((l, i) => {
    if (l.op !== 'same') for (let j = i - 2; j <= i + 2; j++) keep.add(j);
  });
  if (!keep.size) return [lines.slice(0, 20), Math.max(0, lines.length - 20)];
  const out = lines.filter((_, i) => keep.has(i));
  return [out, lines.length - out.length];
}

export function FixedBroken({ proof }: { proof: Proof }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3" data-testid="proof-fixed">
        <p className="text-xs font-medium text-emerald-300">
          Fixed {proof.fixed.length}
          {proof.target_lessons ? ` of ${proof.target_lessons} lessons` : ' lessons'}
        </p>
        {proof.fixed.length ? (
          <ul className="mt-1.5 space-y-1 text-[11px] text-emerald-100/90">
            {proof.fixed.slice(0, 6).map((f) => <li key={f.lesson_id} className="break-words">{f.title || 'A lesson'}</li>)}
            {proof.fixed.length > 6 && <li className="text-emerald-300/70">and {proof.fixed.length - 6} more</li>}
          </ul>
        ) : (
          <p className="mt-1 text-[11px] text-slate-400">None of the lessons it was meant to fix.</p>
        )}
      </div>
      <div
        className={`rounded-lg border p-3 ${proof.broken.length ? 'border-rose-500/40 bg-rose-500/5' : 'border-slate-700 bg-slate-900/40'}`}
        data-testid="proof-broken"
        data-count={proof.broken.length}
      >
        <p className={`text-xs font-medium ${proof.broken.length ? 'text-rose-300' : 'text-slate-300'}`}>
          Newly broken {proof.broken.length}
        </p>
        {proof.broken.length ? (
          <ul className="mt-1.5 space-y-1 text-[11px] text-rose-100/90">
            {proof.broken.slice(0, 6).map((b, i) => (
              <li key={`${b.case_id || 'replay'}-${i}`} className="break-words">
                <span className="font-medium">{b.name}</span>: {b.why}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[11px] text-slate-400">Everything that passed before still passes.</p>
        )}
      </div>
    </div>
  );
}

function Bar({ label, before, after, fmt, lowerIsBetter }: {
  label: string;
  before: number | null;
  after: number | null;
  fmt: (v: number | null) => string;
  lowerIsBetter?: boolean;
}) {
  const max = Math.max(before || 0, after || 0) || 1;
  const better = before !== null && after !== null && (lowerIsBetter ? after < before : after > before);
  const worse = before !== null && after !== null && (lowerIsBetter ? after > before : after < before);
  return (
    <div className="space-y-1" data-testid={`proof-bar-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-slate-300">{label}</span>
        <span className={better ? 'text-emerald-300' : worse ? 'text-amber-300' : 'text-slate-400'}>
          {fmt(before)} to {fmt(after)}
        </span>
      </div>
      <div className="space-y-0.5">
        <div className="h-1.5 rounded bg-slate-800" title={`Before: ${fmt(before)}`}>
          <div className="h-1.5 rounded bg-slate-500" style={{ width: `${((before || 0) / max) * 100}%` }} />
        </div>
        <div className="h-1.5 rounded bg-slate-800" title={`After: ${fmt(after)}`}>
          <div className="h-1.5 rounded bg-cyan-400" style={{ width: `${((after || 0) / max) * 100}%` }} />
        </div>
      </div>
    </div>
  );
}

export function BeforeAfter({ before, after }: { before: Scores; after: Scores }) {
  return (
    <div className="space-y-2.5 rounded-lg border border-slate-800 bg-slate-900/40 p-3" data-testid="proof-before-after">
      <div className="flex items-center gap-3 text-[10px] text-slate-500">
        <span className="inline-flex items-center gap-1"><span className="h-1.5 w-3 rounded bg-slate-500" /> Now</span>
        <span className="inline-flex items-center gap-1"><span className="h-1.5 w-3 rounded bg-cyan-400" /> With the fix</span>
      </div>
      <Bar label="Tests passed" before={before.pass_rate} after={after.pass_rate} fmt={pct} />
      <Bar label="Quality" before={before.quality} after={after.quality} fmt={pct} />
      <Bar label="Cost per run" before={before.cost_usd} after={after.cost_usd} fmt={money} lowerIsBetter />
      <Bar label="Speed" before={before.latency_ms} after={after.latency_ms} fmt={seconds} lowerIsBetter />
      {Math.min(before.timed_runs ?? MIN_SPEED_RUNS, after.timed_runs ?? MIN_SPEED_RUNS) < MIN_SPEED_RUNS && (
        <p className="text-[10px] text-slate-500" data-testid="proof-speed-not-judged">
          Speed is shown but not judged, fewer than {MIN_SPEED_RUNS} runs were timed side by side in this proof.
        </p>
      )}
    </div>
  );
}

export function Examples({ examples }: { examples: Example[] }) {
  if (!examples.length) {
    return <p className="text-xs text-slate-500">No examples changed between the two versions.</p>;
  }
  return (
    <div className="space-y-3" data-testid="proof-examples">
      {examples.slice(0, 3).map((e, i) => (
        <div key={i} className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
          <p className="text-[11px] text-slate-400">
            <span className="text-slate-500">Input: </span>
            <span className="break-words text-slate-200">{e.input}</span>
            {e.verdict === 'fixed' && <span className="ml-2 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] text-emerald-300">fixed</span>}
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Now</p>
              <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-slate-300">{e.before || 'No answer'}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">With the fix</p>
              <p className="mt-0.5 whitespace-pre-wrap break-words text-xs text-slate-200">
                {wordDiff(e.before, e.after).map((w, j) =>
                  w.added ? <mark key={j} className="rounded bg-cyan-500/20 px-0.5 text-cyan-100">{w.text}</mark> : <span key={j}>{w.text}</span>,
                )}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
