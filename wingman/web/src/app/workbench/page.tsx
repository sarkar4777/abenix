'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  ArrowRight, Sparkles, Loader2, Zap, Database, Wifi,
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';
import ExplainerPanel from '../components/ExplainerPanel';
import { WORKBENCH_EXPLAINER } from '../components/explainer-specs';

const ARB_PIPELINE = [
  { id: 'wingman-arb-analyzer', label: 'Arb Analyzer', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'wingman-arb-analyzer agent' },
  { id: 'eia_open_data', label: 'EIA spot', icon: 'db' as const, hint: 'EIA propane / WTI / Brent' },
  { id: 'yahoo_finance', label: 'Forwards', icon: 'db' as const, hint: 'Yahoo futures curve' },
  { id: 'bunker_fuel', label: 'Freight', icon: 'tool' as const, hint: 'shipandbunker.com — bunker-derived' },
  { id: 'open_meteo', label: 'Weather', icon: 'tool' as const, hint: 'Open-Meteo port forecast' },
  { id: 'tavily_search', label: 'News', icon: 'tool' as const, hint: 'Tavily news sentiment' },
  { id: 'financial_calculator', label: 'Calc', icon: 'cpu' as const, hint: 'Net-arb math' },
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
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [briefLoading, setBriefLoading] = useState(true);
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    fetch('/api/wingman/corridors')
      .then((r) => r.json())
      .then((j) => setCorridors(j.data || []))
      .catch(() => {});

    let cancelled = false;
    const loadBrief = (showSpinner: boolean) => {
      if (showSpinner) setBriefLoading(true);
      fetch('/api/wingman/market-brief')
        .then((r) => r.json())
        .then((j) => { if (!cancelled) setBrief(j.data || null); })
        .catch(() => {})
        .finally(() => { if (!cancelled && showSpinner) setBriefLoading(false); });
    };
    loadBrief(true);
    const briefTimer = setInterval(() => loadBrief(false), 30000);

    const live = pollers.current;
    return () => {
      cancelled = true;
      clearInterval(briefTimer);
      Object.values(live).forEach((t) => clearInterval(t));
    };
  }, []);

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
        // Open the DAG drawer immediately so it subscribes while the
        // agent is still running, then poll for the structured result.
        setActiveExecution(data.execution_id);
        setResults((prev) => ({ ...prev, [id]: { ...data, result: null } }));
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
        subtitle="Click Run analysis on any corridor to fire the chain — every step lights up live"
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
          Click <span className="text-emerald-300 font-semibold">Run analysis</span> for a 12-month forward net-arb curve, conviction call, weather + news drivers, and risk band.
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
        className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold transition-colors"
      >
        {running ? (
          <><Loader2 className="w-3 h-3 animate-spin" /> Running pipeline...</>
        ) : (
          <>{hasResult ? 'Re-run detailed analysis' : 'Run detailed analysis'} <ArrowRight className="w-3 h-3" /></>
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
      <div className="flex items-center gap-2 mt-1 text-xs text-slate-400">
        <span className="flex items-center gap-1"><Database className="w-3 h-3 text-emerald-400" />EIA</span>
        <span className="flex items-center gap-1"><Database className="w-3 h-3 text-emerald-400" />Yahoo</span>
        <span className="flex items-center gap-1"><Wifi className="w-3 h-3 text-emerald-400" />AISStream</span>
        <span className="flex items-center gap-1"><Zap className="w-3 h-3 text-amber-400" />Bunker-derived freight</span>
      </div>
      <p className="text-[9px] text-slate-600 mt-1 max-w-md text-right">
        Real public data; freight is a bunker-derived estimate. Production deployments wire Argus / Platts / Baltic feeds.
      </p>
    </div>
  );
}
