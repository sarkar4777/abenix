'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Sparkles, Loader2, ArrowRight, Brain, Newspaper, ExternalLink, Play,
} from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';
import ExplainerPanel from '../components/ExplainerPanel';
import { SCENARIOS_EXPLAINER } from '../components/explainer-specs';

const SCENARIO_PIPELINE = [
  { id: 'wingman-scenario-forecaster', label: 'Forecaster', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'Sonnet 4.5 + Bayesian prior' },
  { id: 'eia_open_data', label: 'EIA spot', icon: 'db' as const, hint: 'origin propane history' },
  { id: 'yahoo_finance', label: 'Forwards', icon: 'db' as const, hint: 'futures curve' },
  { id: 'ml_model', label: 'Bayesian prior', icon: 'cpu' as const, hint: 'wingman-scenario-prior (GaussianNB)' },
  { id: 'tavily_search', label: 'News × 4', icon: 'tool' as const, hint: 'supply / demand / geo / regulatory' },
  { id: 'financial_calculator', label: 'Curve math', icon: 'cpu' as const, hint: 'expected curve + P10/P90' },
];

const SCENARIO_EXPECTED_TOOLS = SCENARIO_PIPELINE
  .filter((p) => !p.id.startsWith('wingman-'))
  .map((p) => ({ id: p.id, label: p.label, hint: p.hint }));

interface Corridor {
  id: string;
  label: string;
  origin_port: string;
  destination_port: string;
  active: boolean;
}

interface CurvePoint { tenor_months: number; date: string; value: number }
interface ExpectedPoint extends CurvePoint { p10?: number; p90?: number }

interface Driver {
  category: string;
  headline: string;
  impact_usd_mt: number;
  source?: string;
  url?: string;
  date?: string;
}

interface Scenario {
  id: string;
  label: string;
  probability: number;
  color: string;
  narrative: string;
  curve: CurvePoint[];
  drivers: Driver[];
}

interface BayesianPrior {
  model: string;
  probabilities: Record<string, number> | null;
}

interface Forecast {
  corridor_id: string;
  as_of: string;
  tenor_months: number;
  base_curve: CurvePoint[];
  expected_curve: ExpectedPoint[];
  feature_vector: Record<string, number>;
  bayesian_prior: BayesianPrior;
  scenarios: Scenario[];
  narrative?: string;
  method?: string;
  data_quality?: string;
  sources?: string[];
}

interface ForecastResponse {
  corridor_id: string;
  execution_id: string;
  status: string;
  forecast: Forecast | null;
  error_message?: string | null;
  failure_code?: string | null;
  cost_usd?: number | null;
  duration_ms?: number | null;
}

const FALLBACK_COLORS: Record<string, string> = {
  base: '#34d399',
  bull_geopolitical: '#60a5fa',
  bear_supply_glut: '#fbbf24',
  bear_demand_shock: '#f97316',
  tail_event: '#f472b6',
};

const SCENARIO_ORDER = [
  'base', 'bull_geopolitical', 'bear_supply_glut', 'bear_demand_shock', 'tail_event',
];

export default function ScenariosPage() {
  const [corridors, setCorridors] = useState<Corridor[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [meta, setMeta] = useState<ForecastResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    fetch('/api/wingman/corridors')
      .then((r) => r.json())
      .then((j) => {
        const list: Corridor[] = (j.data || []).filter((c: Corridor) => c.active);
        setCorridors(list);
        if (list.length > 0 && !selectedId) setSelectedId(list[0].id);
      })
      .catch(() => {});
    const pmap = pollers.current;
    return () => {
      Object.values(pmap).forEach((t) => clearInterval(t));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Pull a cached forecast for the selected corridor (if fresh) so the
  // chart isn't blank when a trader switches corridors.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    fetch(`/api/wingman/scenarios/${selectedId}/cached`)
      .then((r) => r.json())
      .then((j) => {
        if (cancelled) return;
        if (j.data?.forecast) {
          setForecast(j.data.forecast);
          setMeta(null);
          setHighlightId(null);
        } else {
          setForecast(null);
          setMeta(null);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [selectedId]);

  const TERMINAL = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);

  const runForecast = async () => {
    if (!selectedId) return;
    setRunning(true);
    setForecast(null);
    setMeta(null);
    setHighlightId(null);
    try {
      const r = await fetch(`/api/wingman/scenarios/${selectedId}/forecast`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenor_months: 12 }),
      });
      const j = await r.json();
      const execId = j?.data?.execution_id;
      if (!execId) {
        setRunning(false);
        return;
      }
      setActiveExecution(execId);
      const t = setInterval(async () => {
        try {
          const rr = await fetch(`/api/wingman/scenario-result/${execId}`);
          const jj = await rr.json();
          const data: ForecastResponse | undefined = jj?.data;
          if (!data) return;
          if (TERMINAL.has((data.status || '').toLowerCase())) {
            setMeta(data);
            setForecast(data.forecast || null);
            setRunning(false);
            clearInterval(t);
            delete pollers.current[execId];
          }
        } catch { /* keep polling */ }
      }, 2000);
      pollers.current[execId] = t;
    } catch {
      setRunning(false);
    }
  };

  const selected = useMemo(
    () => corridors.find((c) => c.id === selectedId) || null,
    [corridors, selectedId],
  );

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="FORWARD SCENARIOS"
        title="What might happen, weighted"
        subtitle="A Bayesian (GaussianNB) prior over five regimes is refined into a posterior using current supply, demand, geopolitical, and regulatory news. Each scenario's curve, probability, and $/MT drivers are sourced and citable."
        rightSlot={
          <div className="flex flex-col items-end gap-1 text-[10px]">
            <span className="text-slate-500 uppercase tracking-wider">method</span>
            <span className="text-slate-300 font-mono">GaussianNB prior · LLM posterior</span>
          </div>
        }
      />

      <ExplainerPanel spec={SCENARIOS_EXPLAINER} />

      <PipelineStrip
        title="Pipeline · 1 agent · Bayesian prior · 5 real tools"
        subtitle="Click Run forecast on a corridor — Bayesian prior + 4 news searches fire while the curve renders"
        nodes={SCENARIO_PIPELINE}
        executionId={activeExecution}
      />

      {/* Corridor selector + run */}
      <section className="mb-5">
        <div className="flex flex-wrap items-center gap-2">
          {corridors.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedId(c.id)}
              data-testid={`corridor-chip-${c.id}`}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors ${
                selectedId === c.id
                  ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
                  : 'border-slate-800 bg-slate-900/30 text-slate-400 hover:text-white hover:bg-slate-800/40'
              }`}
            >
              {c.label}
            </button>
          ))}
          <div className="flex-1" />
          <button
            onClick={runForecast}
            disabled={!selectedId || running}
            data-testid="run-forecast"
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold"
          >
            {running ? (
              <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Running scenario forecast...</>
            ) : (
              <><Play className="w-3.5 h-3.5" /> Run forecast {selected ? `for ${selected.label}` : ''} <ArrowRight className="w-3 h-3" /></>
            )}
          </button>
        </div>
      </section>

      {/* Failure surfacing — same pattern as the workbench. */}
      {meta?.status?.toLowerCase() === 'failed' && (
        <div className="mb-4 border border-rose-500/30 bg-rose-500/5 rounded-lg p-3 text-[11px] text-rose-200">
          <div className="font-semibold mb-1 uppercase tracking-wider text-[10px]">Forecast failed</div>
          <div className="font-mono break-words text-rose-100/80 leading-relaxed">
            {meta.error_message || 'No error detail returned by the platform.'}
          </div>
        </div>
      )}

      {/* Empty state when nothing has been run */}
      {!forecast && !running && (
        <div className="border border-dashed border-slate-700 rounded-xl p-8 text-center text-[12px] text-slate-500 mb-6">
          Click <span className="text-emerald-300 font-semibold">Run forecast</span> to fire the agent. The Bayesian prior runs first and lights up <span className="font-mono text-cyan-300">ml_model</span> in the live DAG drawer; news searches fire in parallel; the fan chart renders when the agent finishes.
        </div>
      )}

      {/* Forecast came back but with no scenarios array — usually means
          the agent's final JSON was truncated. Surface it instead of
          rendering a blank fan chart. */}
      {forecast && (!forecast.scenarios || forecast.scenarios.length === 0) && (
        <div className="mb-4 border border-amber-500/30 bg-amber-500/5 rounded-lg p-3 text-[11px] text-amber-200">
          <div className="font-semibold mb-1 uppercase tracking-wider text-[10px]">Partial forecast</div>
          <div className="text-amber-100/80 leading-relaxed">
            The agent returned a base curve and Bayesian prior but no scenario detail
            {forecast.bayesian_prior?.probabilities ? '' : ' or prior'}. This usually means the LLM truncated its final JSON envelope under the iteration budget. Re-run the forecast — the cached prior makes the second run faster.
          </div>
        </div>
      )}

      {forecast && (
        <>
          <BayesianPriorStrip forecast={forecast} />
          {forecast.scenarios && forecast.scenarios.length > 0 && (
            <>
              <FanChart
                forecast={forecast}
                highlightId={highlightId}
                onHover={setHighlightId}
              />
              <ScenariosGrid
                forecast={forecast}
                highlightId={highlightId}
                onHover={setHighlightId}
              />
            </>
          )}
          {forecast.narrative && (
            <p className="text-[12px] text-slate-300 italic mt-4 leading-relaxed">{forecast.narrative}</p>
          )}
          {meta && (
            <div className="text-[10px] text-slate-600 mt-3 flex items-center gap-3">
              {meta.execution_id && <span>exec #{meta.execution_id.slice(0, 8)}</span>}
              {meta.cost_usd != null && <span>· ${meta.cost_usd.toFixed(4)}</span>}
              {meta.duration_ms != null && <span>· {Math.round((meta.duration_ms || 0) / 1000)}s</span>}
              {forecast.data_quality && <span>· {forecast.data_quality}</span>}
              {forecast.method && <span className="font-mono">· {forecast.method}</span>}
            </div>
          )}
        </>
      )}

      <DagDrawer
        executionId={activeExecution}
        onClose={() => setActiveExecution(null)}
        expectedTools={SCENARIO_EXPECTED_TOOLS}
      />
    </div>
  );
}

function BayesianPriorStrip({ forecast }: { forecast: Forecast }) {
  const probs = forecast.bayesian_prior?.probabilities || {};
  const features = forecast.feature_vector || {};
  const probEntries = SCENARIO_ORDER
    .filter((id) => id in probs)
    .map((id) => [id, probs[id]] as [string, number]);

  return (
    <div className="mb-4 rounded-xl border border-cyan-500/20 bg-cyan-500/[0.04] p-4">
      <div className="flex items-start justify-between mb-3 gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-cyan-300" />
          <div>
            <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-semibold">
              Bayesian prior
            </div>
            <div className="text-[11px] text-slate-400 font-mono">
              {forecast.bayesian_prior?.model || 'wingman-scenario-prior'}
            </div>
          </div>
        </div>
        <div className="text-[10px] text-slate-500 uppercase tracking-wider">
          GaussianNB · 8 features · {Object.keys(probs).length} classes
        </div>
      </div>

      {probEntries.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-3">
          {probEntries.map(([id, p]) => (
            <div key={id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-2">
              <div className="flex items-center gap-1.5 mb-1">
                <span
                  className="w-1.5 h-1.5 rounded-full inline-block"
                  style={{ background: FALLBACK_COLORS[id] || '#94a3b8' }}
                />
                <span className="text-[9px] uppercase tracking-wider text-slate-500 truncate">{id.replace(/_/g, ' ')}</span>
              </div>
              <div className="text-base font-bold font-mono text-white">{(p * 100).toFixed(0)}%</div>
              <div className="h-1 mt-1 rounded-full bg-slate-800 overflow-hidden">
                <div className="h-full" style={{ width: `${Math.max(0, Math.min(1, p)) * 100}%`, background: FALLBACK_COLORS[id] || '#94a3b8' }} />
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
        {Object.entries(features).map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 px-2 py-1 rounded bg-slate-900/40">
            <span className="text-slate-500 truncate" title={k}>{k}</span>
            <span className="text-slate-200 font-mono">{Number(v).toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function FanChart({
  forecast, highlightId, onHover,
}: {
  forecast: Forecast;
  highlightId: string | null;
  onHover: (id: string | null) => void;
}) {
  // Merge every scenario curve + the expected curve + the p10/p90 band
  // into a single dataset keyed on tenor_months — recharts ComposedChart
  // wants flat rows with one column per series.
  const data = useMemo(() => {
    const tenors = forecast.expected_curve.map((p) => p.tenor_months);
    const base: Record<number, any> = {};
    for (const p of forecast.expected_curve) {
      base[p.tenor_months] = {
        tenor: p.tenor_months,
        date: p.date,
        expected: p.value,
        p10: p.p10 ?? null,
        p90: p.p90 ?? null,
      };
    }
    for (const s of forecast.scenarios) {
      for (const pt of s.curve) {
        if (!base[pt.tenor_months]) {
          base[pt.tenor_months] = { tenor: pt.tenor_months, date: pt.date };
        }
        base[pt.tenor_months][s.id] = pt.value;
      }
    }
    return tenors.map((t) => base[t]).filter(Boolean);
  }, [forecast]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 mb-4">
      <div className="flex items-end justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Forward net-arb · scenario fan</div>
          <div className="text-sm font-bold text-white">
            Expected curve · P10/P90 band · {forecast.scenarios.length} scenarios
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px]">
          {forecast.scenarios.map((s) => {
            const dim = highlightId && highlightId !== s.id;
            return (
              <button
                key={s.id}
                onMouseEnter={() => onHover(s.id)}
                onMouseLeave={() => onHover(null)}
                className={`flex items-center gap-1.5 px-2 py-1 rounded transition-opacity ${
                  dim ? 'opacity-30' : 'opacity-100'
                } bg-slate-800/40`}
              >
                <span className="w-2 h-2 rounded-full" style={{ background: s.color || FALLBACK_COLORS[s.id] || '#94a3b8' }} />
                <span className="text-slate-300">{s.label.split(' — ')[0] || s.id}</span>
                <span className="text-slate-500 font-mono">{(s.probability * 100).toFixed(0)}%</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 12, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis
              dataKey="tenor"
              tick={{ fontSize: 10, fill: '#64748b' }}
              tickFormatter={(t) => `${t}m`}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#64748b' }}
              tickFormatter={(v) => `$${Number(v ?? 0).toFixed(0)}`}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11, borderRadius: 6 }}
              labelStyle={{ color: '#94a3b8' }}
              labelFormatter={(t) => `${t}-month forward`}
              formatter={(v: any, name: any) => [`$${Number(v ?? 0).toFixed(2)}/MT`, String(name ?? '')]}
            />
            {/* P10/P90 band (drawn first so it sits behind the lines).
                Recharts supports a tuple dataKey returning [lower, upper]
                — that yields a true band rather than two stacked areas. */}
            <Area
              type="monotone"
              dataKey={(d: any) => [d.p10 ?? d.expected, d.p90 ?? d.expected]}
              stroke="none"
              fill="#475569"
              fillOpacity={0.18}
              isAnimationActive={false}
              name="P10–P90 band"
            />
            {/* Per-scenario curves. The hovered scenario stays at full
                opacity; everything else dims. */}
            {forecast.scenarios.map((s) => {
              const dim = highlightId && highlightId !== s.id;
              return (
                <Line
                  key={s.id}
                  type="monotone"
                  dataKey={s.id}
                  stroke={s.color || FALLBACK_COLORS[s.id] || '#94a3b8'}
                  strokeWidth={highlightId === s.id ? 2.5 : 1.4}
                  strokeOpacity={dim ? 0.18 : 0.85}
                  dot={false}
                  isAnimationActive={false}
                  name={s.label.split(' — ')[0] || s.id}
                />
              );
            })}
            {/* Probability-weighted expected curve — solid white on top. */}
            <Line
              type="monotone"
              dataKey="expected"
              stroke="#f8fafc"
              strokeWidth={2.5}
              dot={{ r: 2.5, fill: '#f8fafc' }}
              isAnimationActive={false}
              name="Expected (prob-weighted)"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ScenariosGrid({
  forecast, highlightId, onHover,
}: {
  forecast: Forecast;
  highlightId: string | null;
  onHover: (id: string | null) => void;
}) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      {forecast.scenarios.map((s) => {
        const dim = highlightId && highlightId !== s.id;
        const color = s.color || FALLBACK_COLORS[s.id] || '#94a3b8';
        return (
          <motion.div
            key={s.id}
            onMouseEnter={() => onHover(s.id)}
            onMouseLeave={() => onHover(null)}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: dim ? 0.45 : 1, y: 0 }}
            data-testid={`scenario-card-${s.id}`}
            className="rounded-xl border bg-slate-900/30 p-4 transition-opacity"
            style={{ borderColor: highlightId === s.id ? color : '#1e293b' }}
          >
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">{s.id.replace(/_/g, ' ')}</span>
                </div>
                <div className="text-sm font-semibold text-white truncate">{s.label}</div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-2xl font-bold font-mono" style={{ color }}>{(s.probability * 100).toFixed(0)}%</div>
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">posterior</div>
              </div>
            </div>
            <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden mb-3">
              <div className="h-full" style={{ width: `${Math.max(0, Math.min(1, s.probability)) * 100}%`, background: color }} />
            </div>
            <p className="text-[12px] text-slate-300 leading-relaxed mb-3">{s.narrative}</p>
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500">
                <Newspaper className="w-3 h-3" /> Drivers
              </div>
              {s.drivers.slice(0, 4).map((d, i) => (
                <div key={i} className="flex items-start gap-2 px-2 py-1.5 rounded bg-slate-950/40 text-[11px]">
                  <span className="shrink-0 px-1 py-0.5 rounded bg-slate-800 text-slate-400 text-[9px] font-mono uppercase">
                    {d.category}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-slate-200 truncate" title={d.headline}>{d.headline}</div>
                    <div className="text-[9px] text-slate-500 flex gap-2 mt-0.5">
                      {d.source && <span>{d.source}</span>}
                      {d.date && <span>· {d.date}</span>}
                      {d.url && (
                        <a
                          href={d.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-cyan-400 hover:underline flex items-center gap-0.5"
                          onClick={(e) => e.stopPropagation()}
                        >
                          source <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      )}
                    </div>
                  </div>
                  <div
                    className="shrink-0 font-mono text-[10px] font-semibold"
                    style={{ color: d.impact_usd_mt >= 0 ? '#34d399' : '#f87171' }}
                    title="$/MT impact attributed to this driver"
                  >
                    {d.impact_usd_mt >= 0 ? '+' : ''}{d.impact_usd_mt?.toFixed(2)}
                  </div>
                </div>
              ))}
              {s.drivers.length === 0 && (
                <div className="text-[10px] text-slate-600 italic">No drivers attributed.</div>
              )}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
