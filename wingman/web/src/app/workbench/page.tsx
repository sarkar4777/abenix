'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight, Sparkles, Loader2, Zap, Database, Wifi,
  Layers, TrendingDown, Shield, Ship, Activity, Warehouse, Info, ChevronDown,
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';
import ExplainerPanel from '../components/ExplainerPanel';
import { WORKBENCH_EXPLAINER } from '../components/explainer-specs';
import { CacheMeta, readCacheEnvelope, formatAge } from '../components/cache-helpers';
import { useWingmanPageExecution } from '../components/WingmanExecutionsProvider';

const ARB_PIPELINE = [
  { id: 'wingman-arb-analyzer', label: 'Arb Analyzer', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'wingman-arb-analyzer agent (v1.1)' },
  { id: 'eia_open_data', label: 'EIA spot', icon: 'db' as const, hint: 'EIA propane / WTI / Brent' },
  { id: 'yahoo_finance', label: 'Forwards', icon: 'db' as const, hint: 'ICE/CME futures via yfinance' },
  { id: 'bunker_fuel', label: 'Freight', icon: 'tool' as const, hint: 'shipandbunker.com — bunker-derived' },
  { id: 'freight_baltic_blpg', label: 'Baltic BLPG', icon: 'tool' as const, hint: 'BLPG1/2/3 LPG freight assessment' },
  { id: 'vessel_specs', label: 'Vessel specs', icon: 'tool' as const, hint: 'VLGC/LGC/MGC/SGC density + cargo MT' },
  { id: 'options_data', label: 'Options', icon: 'tool' as const, hint: 'Brent + HH IV + 25Δ skew' },
  { id: 'open_meteo', label: 'Weather', icon: 'tool' as const, hint: 'Open-Meteo port forecast' },
  { id: 'tavily_search', label: 'News', icon: 'tool' as const, hint: 'Tavily news sentiment' },
  { id: 'financial_calculator', label: 'Calc', icon: 'cpu' as const, hint: '90d correlations + carry + breakeven' },
];

interface Corridor {
  id: string;
  label: string;
  product: string;
  origin_port: string;
  destination_port: string;
  active: boolean;
}

interface AnalyzeResult {
  corridor_id: string;
  execution_id: string;
  status: string;
  cost_usd?: number;
  duration_ms?: number;
  error_message?: string | null;
  failure_code?: string | null;
  result?: {
    spread_per_mt?: number;
    conviction?: 'HIGH' | 'MEDIUM' | 'LOW' | string;
    unit?: string;
    narrative?: string;
    drivers?: string[];
    sensitivity?: string;
    forward_curve?: Array<{ tenor_months: number; date: string; value: number }>;
    price_components?: {
      origin_price_usd_mt?: number;
      destination_price_usd_mt?: number;
      freight_usd_mt?: number;
      port_fees_usd_mt?: number;
      net_arb_usd_mt?: number;
    };
    risk?: {
      p95_downside_usd_mt?: number;
      p95_upside_usd_mt?: number;
      std_usd_mt?: number;
    };
    cost_stack?: {
      fob_usd_mt?: number | null;
      freight_usd_mt?: number | null;
      canal_toll_usd_mt?: number | null;
      demurrage_usd_mt?: number | null;
      heating_loss_usd_mt?: number | null;
      port_fees_usd_mt?: number | null;
      delivered_total_usd_mt?: number | null;
      destination_spot_usd_mt?: number | null;
      breakeven_edge_usd_mt?: number | null;
      transit_days?: number | null;
      route_class?: string | null;
      method?: string | null;
    };
    roll_yield?: {
      front_value_usd_mt?: number | null;
      back_value_usd_mt?: number | null;
      shape?: 'contango' | 'backwardation' | string;
      monthly_roll_pct?: number | null;
      annualized_roll_pct?: number | null;
      note?: string | null;
    };
    hedge_recipe?: {
      base_cargo_kt?: number | null;
      legs?: Array<{
        instrument?: string;
        exchange?: string;
        direction?: 'long' | 'short' | string;
        ratio_per_mt?: number | null;
        contracts_per_25kt?: number | null;
        correlation_90d?: number | null;
        rationale?: string;
      }>;
      roll_calendar?: string | null;
      residual_basis_risk_pct?: number | null;
      method?: string | null;
    };
    cargo_options?: Array<{
      vessel_class?: string;
      cargo_mt?: number | null;
      freight_usd_mt?: number | null;
      delivered_usd_mt?: number | null;
      net_arb_usd_mt?: number | null;
      verdict?: 'optimal' | 'marginal' | 'loss' | string;
    }>;
    options_overlay?: {
      crude_atm_iv?: number | null;
      crude_rr_25d?: number | null;
      regime?: string | null;
      regime_note?: string | null;
      implied_p95_widen_pct?: number | null;
      vol_anchored_p95_downside_usd_mt?: number | null;
      vol_anchored_p95_upside_usd_mt?: number | null;
      method?: string | null;
    };
    storage_carry?: {
      months_carried?: number | null;
      calendar_spread_usd_mt?: number | null;
      storage_cost_per_mt_month?: number | null;
      total_storage_cost_usd_mt?: number | null;
      net_carry_usd_mt?: number | null;
      verdict?: 'carry_pays' | 'carry_loses' | 'neutral' | string;
      rationale?: string | null;
    };
    weather_summary?: {
      origin?: { hub: string; max_gust_kmh?: number; precip_mm?: number; alert?: string };
      destination?: { hub: string; max_gust_kmh?: number; precip_mm?: number; alert?: string };
    };
    news_headlines?: Array<{ title: string; source?: string; date?: string; url?: string }>;
    data_quality?: string;
    sources?: string[];
  } | null;
}

interface BriefIndicator {
  label: string;
  unit: string;
  latest: number | null;
  wow_change_pct: number | null;
  as_of: string;
  source: string;
  history?: Array<{ date: string; value: number }>;
  region_counts?: Record<string, number>;
  vessels?: Array<{ mmsi: number; name?: string; lat: number; lon: number; region?: string }>;
}

interface MarketBrief {
  indicators: BriefIndicator[];
  narrative?: string;
  data_quality?: string;
  error_message?: string | null;
}

export default function WorkbenchPage() {
  const [corridors, setCorridors] = useState<Corridor[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, AnalyzeResult>>({});
  const [activeExecution, setActiveExecution] = useState<string | null>(null);
  const { registerExecution } = useWingmanPageExecution('arbitrage');
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [briefLoading, setBriefLoading] = useState(true);
  const [cacheMeta, setCacheMeta] = useState<Record<string, CacheMeta>>({});
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const loadCachedForCorridor = (id: string) => {
    return fetch(`/api/wingman/corridors/${id}/cached`)
      .then((r) => r.json())
      .then((j) => {
        const env = readCacheEnvelope(j);
        if (env) {
          setResults((prev) => ({
            ...prev,
            [id]: {
              corridor_id: id,
              execution_id: env.payload.execution_id || '',
              status: 'completed',
              result: env.payload,
              cost_usd: env.payload.cost_usd,
              duration_ms: env.payload.duration_ms,
            } as AnalyzeResult,
          }));
          setCacheMeta((prev) => ({ ...prev, [id]: env.meta }));
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    fetch('/api/wingman/corridors')
      .then((r) => r.json())
      .then((j) => {
        const list = (j.data || []) as Corridor[];
        setCorridors(list);
        list.filter((c) => c.active).forEach((c) => loadCachedForCorridor(c.id));
      })
      .catch(() => {});

    let cancelled = false;
    const loadBrief = (showSpinner: boolean) => {
      if (showSpinner) setBriefLoading(true);
      fetch('/api/wingman/market-brief/cached')
        .then((r) => r.json())
        .then((j) => {
          if (cancelled) return;
          const env = readCacheEnvelope(j);
          if (env) setBrief(env.payload as MarketBrief);
          else {
            return fetch('/api/wingman/market-brief')
              .then((r2) => r2.json())
              .then((j2) => { if (!cancelled) setBrief(j2.data || null); });
          }
        })
        .catch(() => {})
        .finally(() => { if (!cancelled && showSpinner) setBriefLoading(false); });
    };
    loadBrief(true);
    const briefTimer = setInterval(() => loadBrief(false), 30000);

    const cachedTimer = setInterval(() => {
      if (cancelled) return;
      corridors.filter((c) => c.active && running !== c.id).forEach((c) => loadCachedForCorridor(c.id));
    }, 30000);

    const live = pollers.current;
    return () => {
      cancelled = true;
      clearInterval(briefTimer);
      clearInterval(cachedTimer);
      Object.values(live).forEach((t) => clearInterval(t));
    };
  }, [corridors.length, running]);

  const startPolling = (corridorId: string, executionId: string) => {
    if (pollers.current[executionId]) return;
    const t = setInterval(async () => {
      try {
        const r = await fetch(`/api/wingman/analyze-result/${executionId}`);
        const j = await r.json();
        const data: AnalyzeResult = j.data;
        if (!data) return;
        const status = (data.status || '').toLowerCase();
        if (status === 'completed' || status === 'succeeded' || status === 'failed' || status === 'error' || status === 'cancelled') {
          setResults((prev) => ({ ...prev, [corridorId]: data }));
          setRunning((prev) => (prev === corridorId ? null : prev));
          clearInterval(t);
          delete pollers.current[executionId];
        }
      } catch { /* keep polling */ }
    }, 2000);
    pollers.current[executionId] = t;
  };

  const analyze = async (id: string) => {
    setRunning(id);
    try {
      const r = await fetch(`/api/wingman/corridors/${id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenor_months: 12, methodology: 'deep' }),
      });
      const j = await r.json();
      const data: AnalyzeResult = j.data;
      if (data?.execution_id) {
        setActiveExecution(data.execution_id);
        setResults((prev) => ({ ...prev, [id]: { ...data, result: null } }));
        registerExecution({
          pageId: 'arbitrage',
          executionId: data.execution_id,
          agentSlug: 'wingman-arb-analyzer',
          title: corridors.find((c) => c.id === id)?.label || id,
        });
        startPolling(id, data.execution_id);
      } else {
        setRunning(null);
      }
    } catch {
      setRunning(null);
    }
  };

  const active = corridors.filter((c) => c.active);

  return (
    <div className="workbench-grid min-h-screen p-6">
      <HeroBar
        eyebrow="ARBITRAGE WORKBENCH"
        title="Forward net-arb by corridor"
        subtitle="A trader's seat: live propane, freight, weather and news composed into a 12-month forward net-arb curve with conviction and risk band."
        rightSlot={<DataHonestyBadge />}
      />

      <ExplainerPanel spec={WORKBENCH_EXPLAINER} />

      <PipelineStrip
        title="Pipeline · 1 agent · 6 real tools"
        subtitle="Click Run detailed analysis on any corridor to fire the chain — every step lights up live"
        nodes={ARB_PIPELINE}
        executionId={activeExecution}
        onOpenDrawer={() => activeExecution && setActiveExecution(activeExecution)}
      />

      <MarketBriefStrip brief={brief} loading={briefLoading} />

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">Active corridors</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
          {active.map((c) => (
            <CorridorCard
              key={c.id}
              corridor={c}
              result={results[c.id]}
              running={running === c.id}
              onAnalyze={() => analyze(c.id)}
            />
          ))}
        </div>
      </section>

      <DagDrawer
        executionId={activeExecution}
        onClose={() => setActiveExecution(null)}
        expectedTools={ARB_PIPELINE.map((p) => ({ id: p.id, label: p.label, hint: p.hint }))}
      />
    </div>
  );
}

function CorridorCard({
  corridor, result, running, onAnalyze,
}: {
  corridor: Corridor;
  result?: AnalyzeResult;
  running: boolean;
  onAnalyze: () => void;
}) {
  const r = result?.result;
  const spread = r?.spread_per_mt;
  const positive = spread != null && spread >= 0;
  const conviction = (r?.conviction || '').toUpperCase();
  const chip =
    conviction === 'HIGH' ? 'chip-high' :
    conviction === 'MEDIUM' ? 'chip-medium' :
    conviction === 'LOW' ? 'chip-low' : 'chip-medium';
  const hasResult = Boolean(r);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`relative overflow-hidden rounded-xl border ${
        positive ? 'border-emerald-500/30 bg-emerald-500/[0.04]' : 'border-slate-800 bg-slate-900/30'
      } p-5`}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">{corridor.product}</div>
          <div className="text-base font-bold text-white mt-1">{corridor.label}</div>
          <div className="text-[11px] text-slate-500 mt-0.5">{corridor.origin_port} → {corridor.destination_port}</div>
        </div>
        {spread != null ? (
          <div className="text-right">
            <div className={`text-3xl font-bold ${positive ? 'text-emerald-300' : 'text-rose-300'}`}>
              {positive ? '+' : ''}{spread.toFixed(2)}
            </div>
            <div className="text-[10px] text-slate-400">{r?.unit || '$/MT'} · 12m forward</div>
          </div>
        ) : (
          <div className="text-right text-[11px] text-slate-600 italic">
            no analysis yet
          </div>
        )}
      </div>

      {!hasResult && running && (
        <div className="border border-cyan-500/30 bg-cyan-500/5 rounded-lg p-4 mb-3 text-center">
          <Loader2 className="w-4 h-4 text-cyan-300 mx-auto animate-spin" />
          <div className="text-[11px] text-cyan-300 mt-2 font-semibold">Wingman is working — see the live DAG drawer</div>
          <div className="text-[10px] text-slate-500 mt-1">
            Pulling EIA propane history, Brent forward curve, bunker freight, port weather, news sentiment...
          </div>
        </div>
      )}

      {!hasResult && !running && !result?.error_message && (
        <div className="border border-dashed border-slate-700 rounded-lg p-4 mb-3 text-center text-[11px] text-slate-500">
          Click <span className="text-emerald-300 font-semibold">Run detailed analysis</span> for a 12-month forward net-arb curve, conviction call, weather + news drivers, and risk band.
        </div>
      )}

      {/* Surfaced platform-side error so a failed agent stops looking like
          a blank UI bug. The DAG drawer also shows FAILED, but the
          error_message is what tells you why. */}
      {result?.status?.toLowerCase() === 'failed' && (
        <div className="border border-rose-500/30 bg-rose-500/5 rounded-lg p-3 mb-3 text-[11px] text-rose-200">
          <div className="flex items-center gap-1.5 font-semibold mb-1 uppercase tracking-wider text-[10px]">
            Agent failed{result.failure_code && <span className="text-rose-400/70 font-mono normal-case tracking-normal">[{result.failure_code}]</span>}
          </div>
          <div className="text-rose-100/80 break-words font-mono text-[11px] leading-relaxed">
            {result.error_message || 'No error detail returned by the platform — check the agent runtime logs.'}
          </div>
        </div>
      )}

      {/* Forward-curve chart. Null-safe: when the agent reports the
          curve is unavailable (e.g. yahoo_finance tool failed) it
          returns the array with `value: null` — recharts renders that
          as a flat blank panel which looks like a UI bug. Filter to
          numeric points; if none survive, show a clear "unavailable"
          state with the reason from the narrative. */}
      {(() => {
        const fc = (r?.forward_curve || []).filter((p: any) => typeof p?.value === 'number' && Number.isFinite(p.value));
        if (!r?.forward_curve || r.forward_curve.length === 0) return null;
        if (fc.length === 0) {
          return (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 mb-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Forward net-arb curve</div>
              <div className="text-[11px] text-slate-500 italic">
                Curve unavailable for this run — the forwards feed didn't return numeric values. The narrative below explains why; the rest of the brief is unaffected.
              </div>
            </div>
          );
        }
        return (
        <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 mb-3">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Forward net-arb curve</div>
            {r.risk?.std_usd_mt != null && (
              <div className="text-[10px] text-slate-500">σ ${r.risk.std_usd_mt.toFixed(2)}/MT</div>
            )}
          </div>
          <div className="h-32 -mx-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={fc} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={`grad-${corridor.id}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.5} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="tenor_months" tick={{ fontSize: 9, fill: '#64748b' }} axisLine={false} tickLine={false}
                  tickFormatter={(t) => `${t}m`} />
                <YAxis tick={{ fontSize: 9, fill: '#64748b' }} axisLine={false} tickLine={false} width={36}
                  tickFormatter={(v) => `$${v}`} />
                <Tooltip
                  contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11, borderRadius: 6 }}
                  labelStyle={{ color: '#94a3b8' }}
                  labelFormatter={(t) => `${t}-month forward`}
                  formatter={(v: any) => [`$${Number(v ?? 0).toFixed(2)}/MT`, 'net arb']}
                />
                <Area type="monotone" dataKey="value" stroke="#34d399" fill={`url(#grad-${corridor.id})`} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
        );
      })()}

      {/* Price decomposition */}
      {r?.price_components && (
        <div className="grid grid-cols-2 gap-2 mb-3 text-[11px]">
          <PriceTile label="Origin spot" value={r.price_components.origin_price_usd_mt} unit="$/MT" tone="slate" />
          <PriceTile label="Destination" value={r.price_components.destination_price_usd_mt} unit="$/MT" tone="slate" />
          <PriceTile label="Freight (bunker-derived)" value={r.price_components.freight_usd_mt} unit="$/MT" tone="amber" minus />
          <PriceTile label="Net arb" value={r.price_components.net_arb_usd_mt} unit="$/MT" tone={positive ? 'emerald' : 'rose'} bold />
        </div>
      )}

      {/* Risk band */}
      {r?.risk && (r.risk.p95_downside_usd_mt != null || r.risk.p95_upside_usd_mt != null) && (
        <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 mb-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Risk band (P95)</div>
          <div className="flex items-center gap-3 text-[11px]">
            <span className="text-rose-300">↓ ${(r.risk.p95_downside_usd_mt ?? 0).toFixed(2)}</span>
            <div className="flex-1 h-1.5 rounded-full bg-gradient-to-r from-rose-500/40 via-slate-700 to-emerald-500/40" />
            <span className="text-emerald-300">↑ ${(r.risk.p95_upside_usd_mt ?? 0).toFixed(2)}</span>
          </div>
        </div>
      )}

      {/* Conviction + narrative */}
      {r?.narrative && (
        <div className="border border-emerald-500/20 bg-emerald-500/5 rounded-lg p-3 mb-3">
          <div className="flex items-center gap-2 mb-1.5">
            <Sparkles className="w-3 h-3 text-emerald-400" />
            <span className="text-[10px] uppercase tracking-wider font-semibold text-emerald-300">Wingman Intelligence</span>
            {conviction && (
              <span className={`text-[10px] uppercase tracking-wider font-semibold border rounded px-1.5 py-0.5 ${chip}`}>
                {conviction} conviction
              </span>
            )}
          </div>
          <p className="text-xs text-slate-200 leading-relaxed">{r.narrative}</p>
          {r.drivers && r.drivers.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {r.drivers.slice(0, 5).map((d, i) => (
                <li key={i} className="text-[11px] text-slate-300 flex gap-2">
                  <span className="text-emerald-500">·</span>{d}
                </li>
              ))}
            </ul>
          )}
          {r.sensitivity && (
            <p className="text-[10px] text-slate-500 italic mt-2 border-t border-emerald-500/10 pt-2">
              <span className="text-amber-400/80 font-semibold not-italic">Sensitivity: </span>{r.sensitivity}
            </p>
          )}
        </div>
      )}

      {/* Weather + news */}
      {(r?.weather_summary || (r?.news_headlines && r.news_headlines.length > 0)) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
          {r?.weather_summary && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Port weather (next 7d)</div>
              <div className="text-[11px] space-y-1">
                <WeatherRow label={corridor.origin_port} w={r.weather_summary.origin} />
                <WeatherRow label={corridor.destination_port} w={r.weather_summary.destination} />
              </div>
            </div>
          )}
          {r?.news_headlines && r.news_headlines.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">News (last 30d)</div>
              <ul className="space-y-1">
                {r.news_headlines.slice(0, 3).map((h, i) => (
                  <li key={i} className="text-[11px] text-slate-300 leading-snug">
                    {h.url ? (
                      <a href={h.url} target="_blank" rel="noopener noreferrer" className="hover:text-emerald-300">
                        {h.title}
                      </a>
                    ) : h.title}
                    {h.source && <span className="text-slate-600"> · {h.source}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {hasResult && (
        <TraderWorkbenchPanel result={r!} />
      )}

      {r?.sources && r.sources.length > 0 && (
        <div className="text-[9px] text-slate-600 mb-3 flex flex-wrap gap-x-2 gap-y-0.5">
          {r.sources.map((s, i) => (
            <span key={i} className="font-mono">[{s}]</span>
          ))}
        </div>
      )}

      <button
        onClick={onAnalyze}
        disabled={running}
        title={hasResult
          ? `Re-fires the wingman-arb-analyzer v1.1 agent. Typical cost ${result?.cost_usd ? `$${result.cost_usd.toFixed(4)}` : '~$0.04'} · runtime ${result?.duration_ms ? `${Math.round((result.duration_ms || 0) / 1000)}s` : '~60-90s'}`
          : 'Fires the wingman-arb-analyzer v1.1 agent. Typical cost ~$0.04 · runtime ~60-90s (parallel tools).'}
        className="w-full flex flex-col items-center gap-0.5 px-3 py-2 rounded-lg border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold transition-colors"
      >
        {running ? (
          <span className="flex items-center gap-2"><Loader2 className="w-3 h-3 animate-spin" /> Running pipeline...</span>
        ) : (
          <>
            <span className="flex items-center gap-2">{hasResult ? 'Re-run detailed analysis' : 'Run detailed analysis'} <ArrowRight className="w-3 h-3" /></span>
            <span className="text-[9px] text-slate-500 font-normal">
              est. cost {result?.cost_usd ? `$${result.cost_usd.toFixed(4)}` : '~$0.04'} · runtime {result?.duration_ms ? `${Math.round((result.duration_ms || 0) / 1000)}s` : '~60-90s'} · 10 tools in parallel
            </span>
          </>
        )}
      </button>

      {result && (
        <div className="mt-2 text-[10px] text-slate-600 flex items-center gap-2">
          <span>exec #{result.execution_id?.slice(0, 8)}</span>
          {result.cost_usd != null && <span>· ${result.cost_usd.toFixed(4)}</span>}
          {result.duration_ms != null && <span>· {Math.round((result.duration_ms || 0) / 1000)}s</span>}
          {r?.data_quality && <span>· {r.data_quality}</span>}
        </div>
      )}
    </motion.div>
  );
}

function PriceTile({
  label, value, unit, tone, minus, bold,
}: {
  label: string;
  value?: number | null;
  unit: string;
  tone: 'slate' | 'emerald' | 'rose' | 'amber';
  minus?: boolean;
  bold?: boolean;
}) {
  const tones: Record<string, string> = {
    slate: 'text-slate-200 border-slate-800',
    emerald: 'text-emerald-300 border-emerald-500/30',
    rose: 'text-rose-300 border-rose-500/30',
    amber: 'text-amber-300 border-amber-500/20',
  };
  return (
    <div className={`rounded-lg border bg-slate-950/40 px-3 py-2 ${tones[tone]}`}>
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-0.5 ${bold ? 'text-lg font-bold' : 'text-sm font-semibold'}`}>
        {value != null ? `${minus ? '−' : ''}${(value as number).toFixed(2)}` : '—'}
        <span className="text-[10px] text-slate-500 ml-1 font-normal">{unit}</span>
      </div>
    </div>
  );
}

function WeatherRow({ label, w }: { label: string; w?: { hub?: string; max_gust_kmh?: number; precip_mm?: number; alert?: string } }) {
  if (!w) return <div className="text-slate-500">{label}: <span className="italic">no data</span></div>;
  const stormy = (w.max_gust_kmh ?? 0) > 60 || (w.precip_mm ?? 0) > 50 || !!w.alert;
  return (
    <div className="flex justify-between gap-2">
      <span className="text-slate-400">{label}</span>
      <span className={stormy ? 'text-amber-300' : 'text-slate-300'}>
        {w.max_gust_kmh != null && <>{Math.round(w.max_gust_kmh)} km/h gust</>}
        {w.precip_mm != null && <> · {Math.round(w.precip_mm)}mm</>}
        {w.alert && <> · {w.alert}</>}
      </span>
    </div>
  );
}

function MarketBriefStrip({ brief, loading }: { brief: MarketBrief | null; loading: boolean }) {
  // Show every price-style indicator (even ones the upstream feed couldn't
  // resolve right now) so the grid stays balanced. The card itself shows
  // an "unavailable" state for empty histories instead of being filtered
  // out, which used to leave a single lonely card next to 75% empty space.
  const priceIndicators = (brief?.indicators || []).filter(
    (i) => !(i.vessels || i.region_counts),
  );
  const aisIndicator = (brief?.indicators || []).find((i) => i.vessels || i.region_counts);
  // Pad to 4 cards so the lg:grid-cols-4 grid never has empty columns.
  const padded: (BriefIndicator | null)[] = [...priceIndicators];
  while (padded.length < 4) padded.push(null);

  return (
    <section className="mb-8">
      <div className="flex items-end justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Market brief — live</h2>
        <span className="text-[10px] text-slate-600">refreshes every 30s</span>
      </div>
      {loading && !brief ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="border border-slate-800 rounded-xl p-4 bg-slate-900/30 h-28 animate-pulse" />
          ))}
        </div>
      ) : (
        <>
          {brief?.error_message && (
            <div className="border border-rose-500/30 bg-rose-500/5 rounded-lg p-3 mb-3 text-[11px] text-rose-200">
              <div className="font-semibold mb-1 uppercase tracking-wider text-[10px]">Market brief failed</div>
              <div className="text-rose-100/80 break-words font-mono leading-relaxed">{brief.error_message}</div>
            </div>
          )}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-3">
            {padded.slice(0, 4).map((ind, i) =>
              ind ? <PriceSparkCard key={i} ind={ind} /> : <PriceSparkPlaceholder key={i} />,
            )}
          </div>
          {aisIndicator && (
            <VesselScatter ind={aisIndicator} />
          )}
          {brief?.narrative && (
            <p className="text-[11px] text-slate-400 italic mt-3 leading-relaxed">{brief.narrative}</p>
          )}
        </>
      )}
    </section>
  );
}

function PriceSparkPlaceholder() {
  return (
    <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/20 p-3 h-28 flex items-center justify-center">
      <span className="text-[10px] text-slate-600 italic">awaiting feed</span>
    </div>
  );
}

function PriceSparkCard({ ind }: { ind: BriefIndicator }) {
  const wow = ind.wow_change_pct;
  const wowPositive = wow != null && wow >= 0;
  const data = (ind.history || []).map((h) => ({ ...h, value: Number(h.value) }));
  const id = `spark-${ind.label.replace(/[^a-zA-Z0-9]/g, '-')}`;
  const hasData = data.length > 0 && ind.latest != null;
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 h-28 flex flex-col">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">{ind.label}</div>
          <div className="text-lg font-bold text-white mt-0.5">
            {ind.latest != null ? Number(ind.latest).toFixed(ind.unit === '$/gal' ? 3 : 2) : <span className="text-slate-600">—</span>}
            <span className="text-[10px] text-slate-500 ml-1 font-normal">{ind.unit}</span>
          </div>
        </div>
        {wow != null && (
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
            wowPositive ? 'text-emerald-300 bg-emerald-500/10' : 'text-rose-300 bg-rose-500/10'
          }`}>
            {wowPositive ? '+' : ''}{wow.toFixed(2)}%
          </span>
        )}
      </div>
      <div className="flex-1 -mx-1 mt-1 min-h-[36px]">
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 2, right: 2, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={wowPositive ? '#10b981' : '#f43f5e'} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={wowPositive ? '#10b981' : '#f43f5e'} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={['dataMin', 'dataMax']} />
              <Tooltip
                contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11 }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={wowPositive ? '#34d399' : '#fb7185'}
                fill={`url(#${id})`}
                strokeWidth={1.5}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-full flex items-center text-[10px] text-slate-600 italic px-1">
            feed unavailable
          </div>
        )}
      </div>
      <div className="text-[9px] text-slate-600 font-mono truncate mt-1">{ind.source}</div>
    </div>
  );
}

interface Vessel {
  mmsi: number | string;
  name?: string;
  lat: number;
  lon: number;
  region?: string;
}

function VesselScatter({ ind }: { ind: BriefIndicator }) {
  const vessels: Vessel[] = ind.vessels || [];
  // 2:1 equirectangular projection. preserveAspectRatio="xMidYMid meet"
  // keeps every dot in the right relative spot.
  const W = 720;
  const H = 360;
  const x = (lon: number) => ((lon + 180) / 360) * W;
  const y = (lat: number) => ((90 - lat) / 180) * H;
  const colors: Record<string, string> = {
    Americas: '#34d399',
    'NW Europe': '#60a5fa',
    'Middle East': '#fbbf24',
    'Far East': '#f472b6',
    Other: '#94a3b8',
  };
  const regions = ind.region_counts || {};
  const totalVessels = (ind.latest as number) ?? vessels.length;

  const REGION_ANCHORS: { name: string; lon: number; lat: number }[] = [
    { name: 'Americas',    lon: -90, lat: 30 },
    { name: 'NW Europe',   lon: 5,   lat: 55 },
    { name: 'Middle East', lon: 50,  lat: 28 },
    { name: 'Far East',    lon: 130, lat: 30 },
  ];

  const [hover, setHover] = useState<Vessel | null>(null);
  const [pinned, setPinned] = useState<Vessel | null>(null);
  const focused = hover || pinned;

  // Vessels with names rank ahead of the AIS-only "MMSI-N" entries — the
  // panel always has a non-empty list to show even before the user clicks.
  const named = vessels.filter((v) => v.name && !/^MMSI\s/i.test(v.name));
  const fallbackList = (named.length ? named : vessels).slice(0, 8);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
      <div className="flex items-end justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">{ind.label}</div>
          <div className="text-sm font-bold text-white">
            {totalVessels} <span className="text-[10px] text-slate-500 font-normal">{ind.unit}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px]">
          {Object.entries(regions).map(([r, n]) => (
            <span key={r} className="flex items-center gap-1.5 px-1.5 py-0.5 rounded bg-slate-800/40">
              <span className="w-2 h-2 rounded-full inline-block" style={{ background: colors[r] || colors.Other }} />
              <span className="text-slate-300">{r}</span>
              <span className="text-slate-200 font-mono font-semibold">{n as number}</span>
            </span>
          ))}
        </div>
      </div>
      <div className="grid lg:grid-cols-[1fr_220px] gap-3">
        <div className="mx-auto w-full max-w-3xl">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full rounded bg-slate-950/60 aspect-[2/1]"
            preserveAspectRatio="xMidYMid meet"
          >
            {[-60, -30, 0, 30, 60].map((lat) => (
              <line key={`g-${lat}`} x1={0} y1={y(lat)} x2={W} y2={y(lat)} stroke="#1e293b" strokeWidth="0.5" />
            ))}
            {[-150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150].map((lon) => (
              <line key={`m-${lon}`} x1={x(lon)} y1={0} x2={x(lon)} y2={H} stroke="#1e293b" strokeWidth="0.5" />
            ))}
            <line x1={0} y1={y(0)} x2={W} y2={y(0)} stroke="#334155" strokeWidth="1" strokeDasharray="2 4" />
            <line x1={x(0)} y1={0} x2={x(0)} y2={H} stroke="#334155" strokeWidth="1" strokeDasharray="2 4" />
            {REGION_ANCHORS.map((r) => (
              <g key={r.name} opacity="0.55">
                <text x={x(r.lon)} y={y(r.lat)} textAnchor="middle" className="fill-slate-500"
                      style={{ fontSize: 11, fontWeight: 600, letterSpacing: 0.5 }}>
                  {r.name.toUpperCase()}
                </text>
              </g>
            ))}
            {/* Vessel dots — bumped up so sparse points actually register;
                halo widens further on hover/pin so you can tell which one
                you're aiming at. Click pins selection to the side panel. */}
            {vessels.slice(0, 250).map((v, i) => {
              const isFocused = focused?.mmsi === v.mmsi;
              const fill = colors[v.region || 'Other'] || colors.Other;
              return (
                <g
                  key={`${v.mmsi}-${i}`}
                  onMouseEnter={() => setHover(v)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => setPinned((cur) => (cur?.mmsi === v.mmsi ? null : v))}
                  style={{ cursor: 'pointer' }}
                >
                  <circle
                    cx={x(v.lon)}
                    cy={y(v.lat)}
                    r={isFocused ? 14 : 9}
                    fill={fill}
                    opacity={isFocused ? 0.32 : 0.18}
                  />
                  <circle
                    cx={x(v.lon)}
                    cy={y(v.lat)}
                    r={isFocused ? 5.5 : 4}
                    fill={fill}
                    opacity="0.95"
                    stroke={isFocused ? '#f8fafc' : 'transparent'}
                    strokeWidth={isFocused ? 1.5 : 0}
                  >
                    <title>{v.name || v.mmsi} · {v.region} · {v.lat.toFixed(2)}, {v.lon.toFixed(2)}</title>
                  </circle>
                </g>
              );
            })}
          </svg>
        </div>
        <aside className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-[11px] min-h-[140px] flex flex-col">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              {focused ? 'Vessel detail' : 'Live vessels (top)'}
            </div>
            {pinned && (
              <button
                onClick={() => setPinned(null)}
                className="text-[9px] text-slate-500 hover:text-slate-200"
                title="Unpin"
              >
                clear
              </button>
            )}
          </div>
          {focused ? (
            <div className="space-y-1 text-slate-300">
              <div className="font-semibold text-white truncate" title={focused.name || ''}>
                {focused.name || `MMSI ${focused.mmsi}`}
              </div>
              <div className="font-mono text-[10px] text-slate-500">MMSI {focused.mmsi}</div>
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full inline-block" style={{ background: colors[focused.region || 'Other'] || colors.Other }} />
                <span className="text-slate-300">{focused.region || 'Other'}</span>
              </div>
              <div className="font-mono text-[10px] text-slate-500">
                {focused.lat.toFixed(2)}°, {focused.lon.toFixed(2)}°
              </div>
              <div className="pt-2 mt-auto flex flex-col gap-1">
                <a
                  className="text-[10px] text-cyan-300 hover:underline"
                  href={`https://www.vesselfinder.com/?mmsi=${focused.mmsi}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  open on VesselFinder ↗
                </a>
                {pinned?.mmsi !== focused.mmsi && (
                  <button
                    onClick={() => setPinned(focused)}
                    className="text-[10px] text-slate-400 hover:text-slate-100 text-left"
                  >
                    pin to panel
                  </button>
                )}
              </div>
            </div>
          ) : (
            <ul className="space-y-1 overflow-hidden">
              {fallbackList.map((v) => (
                <li key={String(v.mmsi)}>
                  <button
                    onClick={() => setPinned(v)}
                    onMouseEnter={() => setHover(v)}
                    onMouseLeave={() => setHover(null)}
                    className="w-full text-left flex items-center gap-1.5 px-1 py-0.5 rounded hover:bg-slate-800/50"
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full shrink-0"
                      style={{ background: colors[v.region || 'Other'] || colors.Other }}
                    />
                    <span className="truncate text-slate-300">
                      {v.name || `MMSI ${v.mmsi}`}
                    </span>
                  </button>
                </li>
              ))}
              {fallbackList.length === 0 && (
                <li className="text-slate-600 italic text-[10px] my-auto">
                  No vessels in feed right now.
                </li>
              )}
              <li className="text-[9px] text-slate-600 italic pt-1 border-t border-slate-800">
                Click any dot or row to pin its detail + VesselFinder link.
              </li>
            </ul>
          )}
        </aside>
      </div>
      <div className="text-[9px] text-slate-600 font-mono mt-2">{ind.source}</div>
    </div>
  );
}

function DataHonestyBadge() {
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">Data sources</div>
      <div className="flex items-center gap-2 mt-1 text-xs text-slate-400 flex-wrap justify-end">
        <span className="flex items-center gap-1"><Database className="w-3 h-3 text-emerald-400" />EIA</span>
        <span className="flex items-center gap-1"><Database className="w-3 h-3 text-emerald-400" />ICE/CME via yfinance</span>
        <span className="flex items-center gap-1"><Wifi className="w-3 h-3 text-emerald-400" />AISStream</span>
        <span className="flex items-center gap-1"><Database className="w-3 h-3 text-emerald-400" />Baltic BLPG</span>
        <span className="flex items-center gap-1"><Zap className="w-3 h-3 text-amber-400" />Bunker-derived freight</span>
      </div>
      <p className="text-[9px] text-slate-600 mt-1 max-w-md text-right">
        Real public data; freight is a bunker-derived estimate. Canal tolls / demurrage / heating-loss / storage costs are documented industry constants — see widget Method lines. Production deployments wire Argus / Platts / Baltic.
      </p>
    </div>
  );
}

// ── Trader workbench: 6 widgets, real data only ────────────────────────
// Every widget renders ONLY values the agent emitted from real tool
// outputs. If the relevant block is absent, the widget hides. Each
// widget includes a `Method` line explaining the source/formula for
// every number so a trader can audit it.

function TraderWorkbenchPanel({ result }: { result: NonNullable<AnalyzeResult['result']> }) {
  const [open, setOpen] = useState(false);
  const present = {
    cost: !!result.cost_stack,
    roll: !!result.roll_yield,
    hedge: !!(result.hedge_recipe && result.hedge_recipe.legs && result.hedge_recipe.legs.length > 0),
    cargo: !!(result.cargo_options && result.cargo_options.length > 0),
    iv: !!result.options_overlay,
    storage: !!result.storage_carry,
  };
  const count = Object.values(present).filter(Boolean).length;
  if (count === 0) return null;
  return (
    <div className="border border-cyan-500/20 bg-cyan-500/[0.04] rounded-lg mb-3">
      <button
        onClick={() => setOpen((v) => !v)}
        data-testid="trader-workbench-toggle"
        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-[11px] font-semibold text-cyan-300 hover:bg-cyan-500/[0.06] rounded-lg"
      >
        <span className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5" />
          Trader workbench · {count} of 6 widgets ready
        </span>
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="px-3 pb-3 grid grid-cols-1 gap-3">
          {present.cost && <CostStackWidget cs={result.cost_stack!} />}
          {present.iv && <OptionsOverlayWidget ov={result.options_overlay!} fallbackRisk={result.risk} />}
          {present.roll && <RollYieldWidget ry={result.roll_yield!} />}
          {present.storage && <StorageCarryWidget sc={result.storage_carry!} />}
          {present.hedge && <HedgeRecipeWidget hr={result.hedge_recipe!} />}
          {present.cargo && <CargoOptionsWidget rows={result.cargo_options!} />}
        </div>
      )}
    </div>
  );
}

function WidgetShell({
  icon, title, eyebrow, children, method,
}: {
  icon: React.ReactNode;
  title: string;
  eyebrow: string;
  children: React.ReactNode;
  method?: string | null;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <div>
          <div className="text-[9px] uppercase tracking-wider text-cyan-300 font-semibold">{eyebrow}</div>
          <div className="text-[12px] font-bold text-white leading-tight">{title}</div>
        </div>
      </div>
      {children}
      {method && (
        <div className="mt-2 pt-2 border-t border-slate-800 text-[10px] text-slate-500 flex gap-1.5 items-start leading-snug">
          <Info className="w-3 h-3 mt-0.5 shrink-0 text-slate-600" />
          <span><span className="text-slate-400 font-semibold">Method:</span> {method}</span>
        </div>
      )}
    </div>
  );
}

function fmtMoney(n?: number | null, dp = 2): string {
  if (n == null || !Number.isFinite(n as number)) return '—';
  const v = Number(n);
  const sign = v < 0 ? '−' : '';
  return `${sign}$${Math.abs(v).toFixed(dp)}`;
}

function fmtPct(n?: number | null, dp = 2): string {
  if (n == null || !Number.isFinite(n as number)) return '—';
  const v = Number(n);
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(dp)}%`;
}

function CostStackWidget({ cs }: { cs: NonNullable<NonNullable<AnalyzeResult['result']>['cost_stack']> }) {
  const components: Array<{ label: string; value?: number | null; tone: string }> = [
    { label: 'FOB origin spot',  value: cs.fob_usd_mt,          tone: 'bg-emerald-500/50' },
    { label: 'Freight',          value: cs.freight_usd_mt,      tone: 'bg-cyan-500/50' },
    { label: 'Canal toll',       value: cs.canal_toll_usd_mt,   tone: 'bg-amber-500/50' },
    { label: 'Demurrage',        value: cs.demurrage_usd_mt,    tone: 'bg-orange-500/50' },
    { label: 'Heating loss',     value: cs.heating_loss_usd_mt, tone: 'bg-rose-500/40' },
    { label: 'Port fees',        value: cs.port_fees_usd_mt,    tone: 'bg-violet-500/40' },
  ];
  const total = cs.delivered_total_usd_mt ?? components.reduce((a, c) => a + (c.value || 0), 0);
  const dest = cs.destination_spot_usd_mt;
  const edge = cs.breakeven_edge_usd_mt;
  return (
    <WidgetShell
      icon={<Layers className="w-3.5 h-3.5 text-emerald-300" />}
      eyebrow="Delivered cost stack"
      title="What it really costs to deliver this cargo"
      method={cs.method || 'Stack adds FOB + freight + Panama/Suez toll (PCA/SCA published rates) + 4-day demurrage @ Baltic $35k/day for VLGC + heating-loss 0.25%/day × transit × FOB + port fees. Breakeven edge = destination spot − delivered total.'}
    >
      <div className="flex items-center gap-3 mb-2 flex-wrap">
        {cs.route_class && (
          <span className="text-[10px] px-2 py-0.5 rounded border border-slate-800 bg-slate-900/50 text-slate-300 font-mono">
            {cs.route_class}
          </span>
        )}
        {cs.transit_days != null && (
          <span className="text-[10px] text-slate-500 font-mono">{cs.transit_days}-day transit</span>
        )}
      </div>
      <div className="flex h-3 rounded overflow-hidden bg-slate-800/40 mb-2">
        {components.map((c, i) => {
          const pct = total > 0 && c.value != null ? (Math.abs(c.value) / total) * 100 : 0;
          if (pct < 0.5) return null;
          return <div key={i} className={c.tone} style={{ width: `${pct}%` }} title={`${c.label}: ${fmtMoney(c.value)}`} />;
        })}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-1.5 text-[10px] mb-2">
        {components.map((c, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded ${c.tone}`} />
            <span className="text-slate-400 truncate">{c.label}</span>
            <span className="ml-auto font-mono text-slate-200">{fmtMoney(c.value)}</span>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2 mt-2 text-[11px]">
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Delivered total</div>
          <div className="font-mono font-bold text-white">{fmtMoney(total)}<span className="text-[9px] text-slate-500"> /MT</span></div>
        </div>
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Destination spot</div>
          <div className="font-mono font-bold text-white">{fmtMoney(dest)}<span className="text-[9px] text-slate-500"> /MT</span></div>
        </div>
        <div className={`px-2 py-1.5 rounded border ${edge != null && edge >= 0 ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-rose-500/40 bg-rose-500/10'}`}>
          <div className="text-[9px] uppercase text-slate-500">Breakeven edge</div>
          <div className={`font-mono font-bold ${edge != null && edge >= 0 ? 'text-emerald-200' : 'text-rose-200'}`}>{fmtMoney(edge)}<span className="text-[9px] text-slate-500"> /MT</span></div>
        </div>
      </div>
    </WidgetShell>
  );
}

function RollYieldWidget({ ry }: { ry: NonNullable<NonNullable<AnalyzeResult['result']>['roll_yield']> }) {
  const shape = (ry.shape || '').toLowerCase();
  const isContango = shape === 'contango';
  const tone = isContango ? 'text-rose-200 border-rose-500/30 bg-rose-500/10' : 'text-emerald-200 border-emerald-500/30 bg-emerald-500/10';
  return (
    <WidgetShell
      icon={<TrendingDown className="w-3.5 h-3.5 text-amber-300" />}
      eyebrow="Curve shape + roll yield"
      title="What holding the position to the back tenor really pays"
      method={ry.note || 'Shape = contango if back-month > front-month, else backwardation. Monthly roll = (back − front)/front × 100 / months. Annualized = monthly × 12. Computed from the agent\'s forward_curve (yahoo_finance B0=F front-to-12m).'}
    >
      <div className="flex items-center gap-3 flex-wrap mb-2">
        <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${tone} font-bold`}>{shape || 'unknown'}</span>
        {ry.monthly_roll_pct != null && (
          <span className="text-[11px]"><span className="text-slate-500">monthly roll </span><span className={`font-mono font-bold ${ry.monthly_roll_pct >= 0 ? 'text-emerald-200' : 'text-rose-200'}`}>{fmtPct(ry.monthly_roll_pct)}</span></span>
        )}
        {ry.annualized_roll_pct != null && (
          <span className="text-[11px]"><span className="text-slate-500">annualized </span><span className={`font-mono font-bold ${ry.annualized_roll_pct >= 0 ? 'text-emerald-200' : 'text-rose-200'}`}>{fmtPct(ry.annualized_roll_pct)}</span></span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 text-[10px]">
        <div className="px-2 py-1 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Front (M1)</div>
          <div className="font-mono font-bold text-white">{fmtMoney(ry.front_value_usd_mt)}<span className="text-[9px] text-slate-500"> /MT</span></div>
        </div>
        <div className="px-2 py-1 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Back</div>
          <div className="font-mono font-bold text-white">{fmtMoney(ry.back_value_usd_mt)}<span className="text-[9px] text-slate-500"> /MT</span></div>
        </div>
      </div>
    </WidgetShell>
  );
}

function HedgeRecipeWidget({ hr }: { hr: NonNullable<NonNullable<AnalyzeResult['result']>['hedge_recipe']> }) {
  const legs = hr.legs || [];
  if (legs.length === 0) return null;
  return (
    <WidgetShell
      icon={<Shield className="w-3.5 h-3.5 text-violet-300" />}
      eyebrow="Composite hedge recipe"
      title={`Min-variance hedge per ${hr.base_cargo_kt ?? 25}kt cargo`}
      method={hr.method || 'Each correlation_90d is computed from real 90-day daily returns via yahoo_finance + financial_calculator. ratio_per_mt is the minimum-variance hedge fraction. Contracts assume ICE/CME standard sizes (1000 bbl crude, 10k mmBtu HH). Residual basis risk is the unhedgeable propane-specific component.'}
    >
      <div className="overflow-hidden rounded border border-slate-800">
        <table className="w-full text-[10px]">
          <thead className="bg-slate-900/60 text-slate-400">
            <tr>
              <th className="text-left px-2 py-1 font-semibold">Leg</th>
              <th className="text-right px-2 py-1 font-semibold">Side</th>
              <th className="text-right px-2 py-1 font-semibold">ρ 90d</th>
              <th className="text-right px-2 py-1 font-semibold">Ratio /MT</th>
              <th className="text-right px-2 py-1 font-semibold">Contracts</th>
            </tr>
          </thead>
          <tbody className="text-slate-200">
            {legs.map((l, i) => (
              <tr key={i} className="border-t border-slate-800" title={l.rationale}>
                <td className="px-2 py-1">
                  <div className="font-semibold">{l.instrument || '—'}</div>
                  {l.exchange && <div className="text-[9px] text-slate-500 font-mono">{l.exchange}</div>}
                </td>
                <td className="text-right px-2 py-1 font-mono">{l.direction || '—'}</td>
                <td className="text-right px-2 py-1 font-mono">{l.correlation_90d != null ? l.correlation_90d.toFixed(2) : '—'}</td>
                <td className="text-right px-2 py-1 font-mono">{l.ratio_per_mt != null ? l.ratio_per_mt.toFixed(2) : '—'}</td>
                <td className="text-right px-2 py-1 font-mono">{l.contracts_per_25kt ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-2 text-[10px]">
        {hr.roll_calendar && (
          <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800 text-slate-300">
            <span className="text-slate-500 uppercase text-[9px] tracking-wider">Roll calendar · </span>{hr.roll_calendar}
          </div>
        )}
        {hr.residual_basis_risk_pct != null && (
          <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
            <span className="text-slate-500 uppercase text-[9px] tracking-wider">Residual basis risk · </span>
            <span className="font-mono font-bold text-amber-200">{(hr.residual_basis_risk_pct * 100).toFixed(0)}%</span>
            <span className="text-slate-500"> of cargo P&L still uncovered</span>
          </div>
        )}
      </div>
    </WidgetShell>
  );
}

function CargoOptionsWidget({ rows }: { rows: NonNullable<NonNullable<AnalyzeResult['result']>['cargo_options']> }) {
  return (
    <WidgetShell
      icon={<Ship className="w-3.5 h-3.5 text-cyan-300" />}
      eyebrow="Cargo size optimizer"
      title="VLGC vs LGC vs MGC vs SGC for this route"
      method="Each row uses real vessel_specs cargo MT (density-corrected). Freight scales as voyage_cost / cargo_mt — bigger ship = lower $/MT freight because per-voyage costs spread over more cargo. Verdict = optimal at max net arb, marginal within 50% of optimal, loss if negative."
    >
      <div className="overflow-hidden rounded border border-slate-800">
        <table className="w-full text-[10px]">
          <thead className="bg-slate-900/60 text-slate-400">
            <tr>
              <th className="text-left px-2 py-1 font-semibold">Class</th>
              <th className="text-right px-2 py-1 font-semibold">Cargo MT</th>
              <th className="text-right px-2 py-1 font-semibold">Freight $/MT</th>
              <th className="text-right px-2 py-1 font-semibold">Net arb $/MT</th>
              <th className="text-left px-2 py-1 font-semibold">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const v = (r.verdict || '').toLowerCase();
              const tone =
                v === 'optimal' ? 'text-emerald-200' :
                v === 'marginal' ? 'text-amber-200' :
                'text-rose-200';
              return (
                <tr key={i} className="border-t border-slate-800">
                  <td className="px-2 py-1 font-semibold text-slate-200">{r.vessel_class || '—'}</td>
                  <td className="text-right px-2 py-1 font-mono text-slate-200">{r.cargo_mt != null ? r.cargo_mt.toLocaleString() : '—'}</td>
                  <td className="text-right px-2 py-1 font-mono text-slate-200">{fmtMoney(r.freight_usd_mt)}</td>
                  <td className={`text-right px-2 py-1 font-mono font-bold ${(r.net_arb_usd_mt ?? 0) >= 0 ? 'text-emerald-200' : 'text-rose-200'}`}>{fmtMoney(r.net_arb_usd_mt)}</td>
                  <td className={`px-2 py-1 font-semibold uppercase text-[9px] tracking-wider ${tone}`}>{v}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </WidgetShell>
  );
}

function OptionsOverlayWidget({
  ov, fallbackRisk,
}: {
  ov: NonNullable<NonNullable<AnalyzeResult['result']>['options_overlay']>;
  fallbackRisk?: NonNullable<AnalyzeResult['result']>['risk'];
}) {
  const regime = (ov.regime || '').toLowerCase();
  const regimeTone =
    regime === 'skewed_up' ? 'text-rose-200 border-rose-500/40 bg-rose-500/10' :
    regime === 'skewed_down' ? 'text-fuchsia-200 border-fuchsia-500/40 bg-fuchsia-500/10' :
    regime === 'nervous' ? 'text-amber-200 border-amber-500/40 bg-amber-500/10' :
    regime === 'calm' ? 'text-emerald-200 border-emerald-500/40 bg-emerald-500/10' :
    'text-slate-300 border-slate-700/40 bg-slate-800/20';
  const realizedP95Down = fallbackRisk?.p95_downside_usd_mt;
  const realizedP95Up = fallbackRisk?.p95_upside_usd_mt;
  return (
    <WidgetShell
      icon={<Activity className="w-3.5 h-3.5 text-fuchsia-300" />}
      eyebrow="Implied vol overlay"
      title="What the options market is paying for hedges"
      method={ov.method || 'Brent (ICE BZ=F) option chain via options_data. ATM IV = at-the-money 1-month implied vol — market\'s nervousness. 25Δ risk reversal = call IV − put IV. Positive = supply fear (call-skew), negative = demand fear. vol-anchored P95 = realized P95 widened by implied_p95_widen_pct.'}
    >
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] mb-2">
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Brent ATM IV</div>
          <div className="font-mono font-bold text-white">{ov.crude_atm_iv != null ? `${(ov.crude_atm_iv * 100).toFixed(1)}%` : '—'}</div>
        </div>
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">25Δ skew</div>
          <div className={`font-mono font-bold ${(ov.crude_rr_25d ?? 0) >= 0 ? 'text-rose-200' : 'text-fuchsia-200'}`}>{ov.crude_rr_25d != null ? `${ov.crude_rr_25d >= 0 ? '+' : ''}${(ov.crude_rr_25d * 100).toFixed(2)}pp` : '—'}</div>
        </div>
        <div className={`px-2 py-1.5 rounded border ${regimeTone}`}>
          <div className="text-[9px] uppercase text-slate-500">Regime</div>
          <div className="font-mono font-bold uppercase text-[10px]">{regime || '—'}</div>
        </div>
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">P95 widen</div>
          <div className="font-mono font-bold text-amber-200">{ov.implied_p95_widen_pct != null ? `${ov.implied_p95_widen_pct >= 0 ? '+' : ''}${ov.implied_p95_widen_pct.toFixed(1)}%` : '—'}</div>
        </div>
      </div>
      {(ov.vol_anchored_p95_downside_usd_mt != null || ov.vol_anchored_p95_upside_usd_mt != null) && (
        <div className="rounded border border-slate-800 bg-slate-900/40 p-2 mb-1">
          <div className="text-[9px] uppercase text-slate-500 mb-1">Vol-anchored vs realized P95 band</div>
          <div className="grid grid-cols-2 gap-2 text-[10px]">
            <div>
              <div className="text-slate-500">Downside</div>
              <div className="font-mono">
                <span className="text-rose-300 font-bold">{fmtMoney(ov.vol_anchored_p95_downside_usd_mt)}</span>
                {realizedP95Down != null && <span className="text-slate-500"> · realized {fmtMoney(realizedP95Down)}</span>}
              </div>
            </div>
            <div className="text-right">
              <div className="text-slate-500">Upside</div>
              <div className="font-mono">
                <span className="text-emerald-300 font-bold">{fmtMoney(ov.vol_anchored_p95_upside_usd_mt)}</span>
                {realizedP95Up != null && <span className="text-slate-500"> · realized {fmtMoney(realizedP95Up)}</span>}
              </div>
            </div>
          </div>
        </div>
      )}
      {ov.regime_note && <p className="text-[10px] text-slate-400 italic leading-snug mt-1">{ov.regime_note}</p>}
    </WidgetShell>
  );
}

function StorageCarryWidget({ sc }: { sc: NonNullable<NonNullable<AnalyzeResult['result']>['storage_carry']> }) {
  const verdict = (sc.verdict || '').toLowerCase();
  const tone =
    verdict === 'carry_pays' ? 'text-emerald-200 border-emerald-500/40 bg-emerald-500/10' :
    verdict === 'carry_loses' ? 'text-rose-200 border-rose-500/40 bg-rose-500/10' :
    'text-slate-300 border-slate-700/40 bg-slate-800/20';
  return (
    <WidgetShell
      icon={<Warehouse className="w-3.5 h-3.5 text-violet-300" />}
      eyebrow="Storage carry economics"
      title="Hold-vs-sell decision against the curve"
      method={sc.rationale ||
        'Calendar spread = back-month − front-month from yahoo_finance forward curve. Storage cost = LPG terminal industry-standard ~$0.50/MT/month. Net carry = spread − total storage. Carry pays only when spread > storage cost.'}
    >
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] mb-2">
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Months</div>
          <div className="font-mono font-bold text-white">{sc.months_carried ?? '—'}</div>
        </div>
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Calendar spread</div>
          <div className={`font-mono font-bold ${(sc.calendar_spread_usd_mt ?? 0) >= 0 ? 'text-emerald-200' : 'text-rose-200'}`}>{fmtMoney(sc.calendar_spread_usd_mt)}</div>
        </div>
        <div className="px-2 py-1.5 rounded bg-slate-900/60 border border-slate-800">
          <div className="text-[9px] uppercase text-slate-500">Storage cost</div>
          <div className="font-mono font-bold text-amber-200">{fmtMoney(sc.total_storage_cost_usd_mt)}</div>
        </div>
        <div className={`px-2 py-1.5 rounded border ${tone}`}>
          <div className="text-[9px] uppercase text-slate-500">Net carry · {verdict || '—'}</div>
          <div className={`font-mono font-bold ${(sc.net_carry_usd_mt ?? 0) >= 0 ? 'text-emerald-200' : 'text-rose-200'}`}>{fmtMoney(sc.net_carry_usd_mt)}</div>
        </div>
      </div>
    </WidgetShell>
  );
}
