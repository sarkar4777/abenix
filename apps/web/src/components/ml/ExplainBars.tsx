'use client';

export interface Contribution {
  feature: string;
  value: number;
  baseline: number;
  contribution: number;
}

export interface Explanation {
  method: string;
  target?: string;
  prediction: number;
  base_value: number;
  baseline_source?: string;
  contributions: Contribution[];
}

const METHOD_LABEL: Record<string, string> = {
  linear: 'exact, from the model coefficients',
  'linear-shap': 'exact, from the model coefficients',
  'tree-shap': 'exact, from the trees',
  'exact-shapley': 'exact Shapley values',
  'sampled-shapley': 'Shapley values, sampled',
};

function fmt(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  const a = Math.abs(n);
  if (a !== 0 && (a < 0.001 || a >= 1e6)) return n.toExponential(2);
  return Number(n.toPrecision(4)).toString();
}

/** Which features pushed this prediction up or down from the baseline, largest first. */
export function topContributions(e: Explanation, limit = 10): { shown: Contribution[]; rest: number; restCount: number } {
  const sorted = [...(e.contributions || [])].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const shown = sorted.slice(0, limit);
  const others = sorted.slice(limit);
  return { shown, rest: others.reduce((s, c) => s + c.contribution, 0), restCount: others.length };
}

export default function ExplainBars({ explanation }: { explanation: Explanation }) {
  const { shown, rest, restCount } = topContributions(explanation);
  const peak = Math.max(1e-12, ...shown.map((c) => Math.abs(c.contribution)), Math.abs(rest));
  const method = METHOD_LABEL[explanation.method] || explanation.method;

  return (
    <div className="mt-3 rounded-lg bg-slate-900/60 border border-slate-700/50 p-3" data-testid="ml-explain-result">
      <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3">
        <p className="text-xs text-slate-300">
          From a baseline of <strong className="text-white font-mono">{fmt(explanation.base_value)}</strong> to{' '}
          <strong className="text-cyan-300 font-mono">{fmt(explanation.prediction)}</strong>
          {explanation.target ? <span className="text-slate-500"> ({explanation.target})</span> : null}
        </p>
        <p className="text-[10px] text-slate-500">{method}</p>
      </div>
      <ul className="space-y-1.5" aria-label="Feature contributions">
        {shown.map((c) => {
          const pct = (Math.abs(c.contribution) / peak) * 50;
          const up = c.contribution >= 0;
          return (
            <li key={c.feature} className="grid grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-2 text-[11px]" data-testid="ml-explain-row">
              <span className="truncate text-slate-300" title={`${c.feature} = ${fmt(c.value)} (baseline ${fmt(c.baseline)})`}>
                {c.feature} <span className="text-slate-500 font-mono">{fmt(c.value)}</span>
              </span>
              <span className="relative h-3.5 rounded bg-slate-800/60 overflow-hidden">
                <span className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
                <span
                  className={`absolute inset-y-0.5 rounded-sm ${up ? 'bg-gradient-to-r from-cyan-500/70 to-cyan-300' : 'bg-gradient-to-l from-rose-500/70 to-rose-300'}`}
                  style={up ? { left: '50%', width: `${pct}%` } : { right: '50%', width: `${pct}%` }}
                />
              </span>
              <span className={`text-right font-mono ${up ? 'text-cyan-300' : 'text-rose-300'}`}>
                {up ? '+' : ''}{fmt(c.contribution)}
              </span>
            </li>
          );
        })}
        {restCount > 0 && (
          <li className="grid grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-2 text-[11px] text-slate-500">
            <span>{restCount} other feature{restCount === 1 ? '' : 's'}</span>
            <span />
            <span className="text-right font-mono">{rest >= 0 ? '+' : ''}{fmt(rest)}</span>
          </li>
        )}
      </ul>
      <p className="mt-2 text-[10px] text-slate-500">Bars to the right pushed this prediction up, bars to the left pulled it down.</p>
    </div>
  );
}
