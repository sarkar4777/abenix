'use client';

export interface Scenario {
  name: string;
  probability?: number;
  impact?: string | number;
  description?: string;
  direction?: 'bull' | 'bear' | 'base' | 'tail' | string;
}

const TONE: Record<string, string> = {
  bull: 'border-emerald-500/40 bg-emerald-500/5 text-emerald-200',
  bear: 'border-rose-500/40 bg-rose-500/5 text-rose-200',
  base: 'border-slate-700 bg-slate-800/30 text-slate-200',
  tail: 'border-amber-500/40 bg-amber-500/5 text-amber-200',
};

function toneFor(s: Scenario): string {
  if (s.direction && TONE[s.direction]) return TONE[s.direction];
  const lower = (s.name || '').toLowerCase();
  if (lower.includes('bull')) return TONE.bull;
  if (lower.includes('bear')) return TONE.bear;
  if (lower.includes('tail') || lower.includes('geopol')) return TONE.tail;
  return TONE.base;
}

function fmtProb(p?: number): string {
  if (p == null || isNaN(p)) return '—';
  const v = p > 1 ? p : p * 100;
  return `${v.toFixed(0)}%`;
}

export function ScenarioCard({ scenario }: { scenario: Scenario }) {
  const tone = toneFor(scenario);
  return (
    <div
      data-testid="scenario-card"
      className={`rounded-lg border p-3 ${tone}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider">
          {scenario.name || 'Scenario'}
        </p>
        <span className="text-[10px] font-mono opacity-80">{fmtProb(scenario.probability)}</span>
      </div>
      {scenario.impact != null && (
        <p className="text-sm font-mono mt-1">{String(scenario.impact)}</p>
      )}
      {scenario.description && (
        <p className="text-[11px] mt-1 opacity-80 leading-relaxed">{scenario.description}</p>
      )}
    </div>
  );
}

export function ScenarioList({ scenarios }: { scenarios?: Scenario[] }) {
  if (!scenarios || scenarios.length === 0) {
    return (
      <div
        data-testid="scenario-empty"
        className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-xs text-slate-500"
      >
        No scenarios yet — run analysis to populate.
      </div>
    );
  }
  return (
    <div data-testid="scenario-list" className="space-y-2">
      {scenarios.map((s, i) => (
        <ScenarioCard key={`${s.name || 'sc'}-${i}`} scenario={s} />
      ))}
    </div>
  );
}

export default ScenarioCard;
