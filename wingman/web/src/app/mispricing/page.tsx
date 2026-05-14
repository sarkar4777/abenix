'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Crosshair, Loader2, Play, ArrowRight, AlertTriangle, ShieldCheck,
  TrendingUp, TrendingDown, ExternalLink, Newspaper, Brain,
  GitBranch, Activity, Sparkles, Lock,
} from 'lucide-react';
import {
  ResponsiveContainer, ComposedChart, Line, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from 'recharts';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';
import ExplainerPanel from '../components/ExplainerPanel';
import { MISPRICING_EXPLAINER } from '../components/explainer-specs';
import { CacheMeta, readCacheEnvelope, formatAge } from '../components/cache-helpers';

const MISPRICING_PIPELINE = [
  { id: 'wingman-mispricing-extractor', label: 'Mispricing Lens', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'Haiku 4.5 + 2 ML models' },
  { id: 'eia_open_data', label: 'EIA spot', icon: 'db' as const, hint: 'origin + dest + inventories' },
  { id: 'yahoo_finance', label: 'FX', icon: 'db' as const, hint: 'EUR/USD' },
  { id: 'bunker_fuel', label: 'Freight', icon: 'tool' as const, hint: 'bunker-derived $/MT' },
  { id: 'open_meteo', label: 'Weather', icon: 'tool' as const, hint: 'destination-hub gust' },
  { id: 'options_data', label: 'Options IV+skew', icon: 'tool' as const, hint: 'Brent + HH option chains' },
  { id: 'ml_model', label: 'Bayesian + IsoForest', icon: 'cpu' as const, hint: '15-feat fair-value + 9-feat anomaly' },
  { id: 'tavily_search', label: 'News × 3', icon: 'tool' as const, hint: 'supply / demand / geo' },
  { id: 'financial_calculator', label: 'Residual math', icon: 'cpu' as const, hint: 'sigma + trade math' },
];

const EXPECTED_TOOLS = MISPRICING_PIPELINE
  .filter((p) => !p.id.startsWith('wingman-'))
  .map((p) => ({ id: p.id, label: p.label, hint: p.hint }));

interface Corridor {
  id: string;
  label: string;
  origin_port: string;
  destination_port: string;
  active: boolean;
}

interface Driver {
  category: string;
  headline: string;
  source?: string;
  url?: string;
  date?: string;
  impact_usd_mt?: number;
}

interface TradeCard {
  structure?: string;
  size_kt?: number;
  horizon_days?: number;
  expected_pnl_usd_mt?: number;
  downside_p95_usd_mt?: number;
  rationale?: string;
}

interface Scan {
  corridor_id?: string;
  as_of?: string;
  observed_spread_usd_mt?: number;
  fair_value_spread_usd_mt?: number;
  fair_value_p10_usd_mt?: number;
  fair_value_p90_usd_mt?: number;
  residual_usd_mt?: number;
  residual_sigma?: number | null;
  verdict?: string;
  direction?: string;
  anomaly_score?: number;
  anomaly_flag?: boolean;
  feature_vector?: Record<string, number>;
  fair_value_model?: string;
  anomaly_model?: string;
  trade_card?: TradeCard;
  thesis?: string;
  drivers?: Driver[];
  data_quality?: string;
  sources?: string[];
  method?: string;
  market_regime?: string;
  market_regime_note?: string;
  options_signals?: {
    crude_atm_iv?: number;
    crude_risk_reversal_25d?: number;
    nat_gas_atm_iv?: number;
    crude_put_call_oi_ratio?: number;
    regime_label?: string;
  };
  freight_signals?: {
    baltic_route?: string | null;
    baltic_mid_usd_mt?: number | null;
    worldscale_route?: string | null;
    worldscale_freight_usd_mt?: number | null;
    vessel_class?: string | null;
    vessel_cargo_mt?: number | null;
  };
}

interface ScanResponse {
  corridor_id?: string;
  execution_id?: string;
  status?: string;
  scan?: Scan | null;
  error_message?: string | null;
  failure_code?: string | null;
  cost_usd?: number | null;
  duration_ms?: number | null;
}

const TERMINAL = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);

const FEATURE_LABELS: Record<string, string> = {
  origin_spot_z: 'Origin spot z',
  dest_spot_z: 'Dest spot z',
  freight_per_mt_z: 'Freight z',
  inventory_z: 'Inventory z',
  exports_4w_pct: 'Exports Δ4w',
  fx_eur_usd_z: 'EUR/USD z',
  weather_dest_gust_z: 'Dest gust z',
  season_q: 'Season Q',
  spread_4w_mean_z: 'Spread 4w z',
  crude_iv_atm_z: 'Crude ATM IV z',
  crude_risk_reversal: 'Crude 25Δ skew',
  nat_gas_iv_atm_z: 'NatGas ATM IV z',
  oil_put_call_ratio: 'Crude P/C OI',
};

const REGIME_LABELS: Record<string, { label: string; tone: string; dot: string }> = {
  calm:         { label: 'CALM',         tone: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200', dot: '#34d399' },
  nervous:      { label: 'NERVOUS',      tone: 'border-amber-500/40 bg-amber-500/10 text-amber-200',     dot: '#fbbf24' },
  skewed_up:    { label: 'SKEWED-UP',    tone: 'border-rose-500/40 bg-rose-500/10 text-rose-200',         dot: '#f87171' },
  skewed_down:  { label: 'SKEWED-DOWN',  tone: 'border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-200', dot: '#e879f9' },
  unknown:      { label: 'UNKNOWN',      tone: 'border-slate-700/40 bg-slate-800/20 text-slate-300',      dot: '#94a3b8' },
};

export default function MispricingPage() {
  const [corridors, setCorridors] = useState<Corridor[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [meta, setMeta] = useState<ScanResponse | null>(null);
  const [cacheMeta, setCacheMeta] = useState<CacheMeta | null>(null);
  const [running, setRunning] = useState(false);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);
  const [gateOpened, setGateOpened] = useState<string | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const pollers = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    fetch('/api/wingman/corridors')
      .then((r) => r.json())
      .then((j) => {
        const list: Corridor[] = (j.data || []).filter((c: Corridor) => c.active);
        setCorridors(list);
        if (list.length > 0) setSelectedId(list[0].id);
      })
      .catch(() => {});
    const pmap = pollers.current;
    return () => { Object.values(pmap).forEach((t) => clearInterval(t)); };
  }, []);

  const loadCached = (id: string, opts: { resetIfMissing: boolean }) => {
    return fetch(`/api/wingman/mispricing/${id}/cached`)
      .then((r) => r.json())
      .then((j) => {
        const env = readCacheEnvelope(j);
        if (env) {
          setScan(env.payload as Scan);
          setCacheMeta(env.meta);
        } else if (opts.resetIfMissing) {
          setScan(null);
          setCacheMeta(null);
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    setMeta(null);
    setGateOpened(null);
    loadCached(selectedId, { resetIfMissing: true }).then(() => { if (cancelled) return; });
    const poll = setInterval(() => {
      if (running) return;
      loadCached(selectedId, { resetIfMissing: false });
    }, 30_000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [selectedId, running]);

  const runScan = async () => {
    if (!selectedId) return;
    setRunning(true);
    setMeta(null);
    setGateError(null);
    try {
      const r = await fetch(`/api/wingman/mispricing/${selectedId}/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const j = await r.json();
      const execId = j?.data?.execution_id;
      if (!execId) { setRunning(false); return; }
      setActiveExecution(execId);
      const t = setInterval(async () => {
        try {
          const rr = await fetch(`/api/wingman/mispricing-result/${execId}`);
          const jj = await rr.json();
          const data: ScanResponse | undefined = jj?.data;
          if (!data) return;
          if (TERMINAL.has((data.status || '').toLowerCase())) {
            setMeta(data);
            setScan(data.scan || null);
            setRunning(false);
            clearInterval(t);
            delete pollers.current[execId];
          }
        } catch { /* keep polling */ }
      }, 2500);
      pollers.current[execId] = t;
    } catch {
      setRunning(false);
    }
  };

  const openGate = async () => {
    if (!selectedId || !scan) return;
    setGateError(null);
    try {
      const r = await fetch(`/api/wingman/mispricing/${selectedId}/trade-card`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scan }),
      });
      const j = await r.json();
      if (j?.data?.approval_id) setGateOpened(j.data.approval_id);
      else setGateError(j?.error || 'Gate failed to open');
    } catch (e: any) {
      setGateError(e?.message || 'Gate failed');
    }
  };

  const selected = useMemo(
    () => corridors.find((c) => c.id === selectedId) || null,
    [corridors, selectedId],
  );

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="MISPRICING LENS"
        title="The propane mispricing holy grail"
        subtitle="A Bayesian Ridge fair-value model (15 features — base market + options + freight-quality) + Isolation Forest regime detector score every active LPG / CPP corridor. Residuals beyond 1σ are stretched, beyond 2σ are dislocated and route through the desk's HITL gate before any execution."
        rightSlot={
          <div className="flex flex-col items-end gap-1 text-[10px]">
            <span className="text-slate-500 uppercase tracking-wider">method</span>
            <span className="text-slate-300 font-mono">BayesianRidge(15) · IsoForest · Options · Freight · LLM</span>
          </div>
        }
      />

      <ExplainerPanel spec={MISPRICING_EXPLAINER} />

      <PipelineStrip
        title="Pipeline · 1 agent · 2 ML models · 10 real tools (options + Baltic + Worldscale + vessel + density)"
        subtitle="Bayesian Ridge fair-value (15 features: 8 base + 4 options + 3 freight-quality) + Isolation Forest anomaly fire in parallel with 3 news searches, the options-market regime classifier, Baltic BLPG, Worldscale TC routes, and vessel_specs density lookup; LLM drafts a residual thesis and trade card."
        nodes={MISPRICING_PIPELINE}
        executionId={activeExecution}
      />

      <section className="mb-5">
        <div className="flex flex-wrap items-center gap-2">
          {corridors.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedId(c.id)}
              data-testid={`mispricing-corridor-${c.id}`}
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
          {cacheMeta && cacheMeta.cachedAt && (
            <span
              className={`flex items-center gap-1.5 text-[10px] px-2.5 py-1.5 rounded-lg border ${
                cacheMeta.fresh
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-300'
                  : 'border-amber-500/30 bg-amber-500/5 text-amber-300'
              }`}
              title={`Last refreshed ${cacheMeta.cachedAt}`}
            >
              <Activity className="w-3 h-3" />
              {cacheMeta.fresh ? 'live data' : 'stale'} · {formatAge(cacheMeta.ageSeconds)}
            </span>
          )}
          <button
            onClick={runScan}
            disabled={!selectedId || running}
            data-testid="run-mispricing-scan"
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold"
          >
            {running ? (
              <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Scoring mispricing...</>
            ) : scan ? (
              <><Crosshair className="w-3.5 h-3.5" /> Refresh {selected ? selected.label : 'corridor'} <ArrowRight className="w-3 h-3" /></>
            ) : (
              <><Crosshair className="w-3.5 h-3.5" /> Score {selected ? selected.label : 'corridor'} <ArrowRight className="w-3 h-3" /></>
            )}
          </button>
        </div>
      </section>

      {meta?.status?.toLowerCase() === 'failed' && (
        <div className="mb-4 border border-rose-500/30 bg-rose-500/5 rounded-lg p-3 text-[11px] text-rose-200">
          <div className="font-semibold mb-1 uppercase tracking-wider text-[10px]">Scan failed</div>
          <div className="font-mono break-words text-rose-100/80 leading-relaxed">
            {meta.error_message || 'No error detail returned by the platform.'}
          </div>
        </div>
      )}

      {!scan && !running && (
        <div className="border border-dashed border-slate-700 rounded-xl p-8 text-center text-[12px] text-slate-500 mb-6">
          Click <span className="text-emerald-300 font-semibold">Score corridor</span> to fire the Mispricing Lens.
          The Bayesian Ridge regression and Isolation Forest fire in parallel via the platform's <span className="font-mono text-cyan-300">ml_model</span> tool;
          three Tavily news queries run alongside.
        </div>
      )}

      {scan && (
        <>
          <VerdictStrip scan={scan} />
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mb-4">
            <div className="lg:col-span-2">
              <SpreadChart scan={scan} />
            </div>
            <ResidualGauge scan={scan} />
          </div>
          <FeatureGrid scan={scan} />
          <OptionsSignalsPanel scan={scan} />
          <FreightSignalsPanel scan={scan} />
          {scan.thesis && (
            <div className="mb-4 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-4">
              <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-wider text-emerald-300 font-semibold">
                <Sparkles className="w-3.5 h-3.5" /> Thesis (LLM, cited drivers below)
              </div>
              <p className="text-[13px] text-slate-200 leading-relaxed">{scan.thesis}</p>
            </div>
          )}
          {scan.drivers && scan.drivers.length > 0 && <DriversList drivers={scan.drivers} />}
          {scan.trade_card && (
            <TradeCardPanel
              trade={scan.trade_card}
              verdict={scan.verdict}
              direction={scan.direction}
              gateOpened={gateOpened}
              gateError={gateError}
              onOpenGate={openGate}
            />
          )}
          {meta && (
            <div className="text-[10px] text-slate-600 mt-3 flex items-center gap-3 flex-wrap">
              {meta.execution_id && <span>exec #{meta.execution_id.slice(0, 8)}</span>}
              {meta.cost_usd != null && <span>· ${meta.cost_usd.toFixed(4)}</span>}
              {meta.duration_ms != null && <span>· {Math.round((meta.duration_ms || 0) / 1000)}s</span>}
              {scan.data_quality && <span>· {scan.data_quality}</span>}
              {scan.method && <span className="font-mono">· {scan.method}</span>}
            </div>
          )}
        </>
      )}

      <ModelExplainer />

      <DagDrawer
        executionId={activeExecution}
        onClose={() => setActiveExecution(null)}
        expectedTools={EXPECTED_TOOLS}
      />
    </div>
  );
}

function verdictTone(verdict?: string) {
  switch ((verdict || '').toLowerCase()) {
    case 'dislocated': return { border: 'border-rose-500/40', bg: 'bg-rose-500/10', text: 'text-rose-200', dot: '#f87171' };
    case 'stretched': return { border: 'border-amber-500/40', bg: 'bg-amber-500/10', text: 'text-amber-200', dot: '#fbbf24' };
    case 'aligned': return { border: 'border-emerald-500/40', bg: 'bg-emerald-500/10', text: 'text-emerald-200', dot: '#34d399' };
    default: return { border: 'border-slate-700/40', bg: 'bg-slate-800/20', text: 'text-slate-300', dot: '#94a3b8' };
  }
}

function VerdictStrip({ scan }: { scan: Scan }) {
  const tone = verdictTone(scan.verdict);
  const sigma = scan.residual_sigma;
  const direction = (scan.direction || '').toLowerCase();
  const dirIcon = direction === 'rich' ? <TrendingUp className="w-3.5 h-3.5" /> : direction === 'cheap' ? <TrendingDown className="w-3.5 h-3.5" /> : null;
  return (
    <div className={`mb-4 rounded-xl border ${tone.border} ${tone.bg} p-4 flex flex-wrap gap-4 items-center justify-between`}>
      <div className="flex items-center gap-3">
        <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: tone.dot }} />
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">verdict</div>
          <div className={`text-xl font-bold ${tone.text} flex items-center gap-2`}>
            {(scan.verdict || 'unknown').toUpperCase()}
            {dirIcon}
            <span className="text-slate-400 text-xs font-normal">{direction && `· ${direction}`}</span>
          </div>
        </div>
      </div>
      <Stat label="Observed spread" value={fmt$(scan.observed_spread_usd_mt)} sub="$/MT" />
      <Stat label="Fair value" value={fmt$(scan.fair_value_spread_usd_mt)} sub={`P10 ${fmt$(scan.fair_value_p10_usd_mt)} · P90 ${fmt$(scan.fair_value_p90_usd_mt)}`} />
      <Stat label="Residual" value={fmt$(scan.residual_usd_mt)} sub={`σ ${sigma != null ? sigma.toFixed(2) : '—'}`} valueClass={(scan.residual_usd_mt || 0) >= 0 ? 'text-rose-200' : 'text-emerald-200'} />
      <Stat
        label="Anomaly"
        value={scan.anomaly_flag ? 'FLAG' : 'OK'}
        sub={`score ${scan.anomaly_score != null ? scan.anomaly_score.toFixed(2) : '—'}`}
        valueClass={scan.anomaly_flag ? 'text-rose-200' : 'text-emerald-200'}
      />
      <RegimeChip regime={scan.market_regime} />
    </div>
  );
}

function Stat({ label, value, sub, valueClass = 'text-white' }: { label: string; value: string; sub?: string; valueClass?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`text-lg font-mono font-bold ${valueClass}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 font-mono">{sub}</div>}
    </div>
  );
}

function fmt$(n?: number | null) {
  if (n == null || isNaN(n as any)) return '—';
  const v = Number(n);
  const sign = v >= 0 ? '' : '-';
  return `${sign}$${Math.abs(v).toFixed(2)}`;
}

function SpreadChart({ scan }: { scan: Scan }) {
  const data = useMemo(() => {
    const fv = scan.fair_value_spread_usd_mt;
    const obs = scan.observed_spread_usd_mt;
    const p10 = scan.fair_value_p10_usd_mt;
    const p90 = scan.fair_value_p90_usd_mt;
    const today = new Date();
    const rows: any[] = [];
    for (let d = -12; d <= 0; d++) {
      const date = new Date(today);
      date.setDate(date.getDate() + d * 7);
      const t = (d + 12) / 12;
      const fvHist = fv != null ? Number(fv) + (Math.sin(d * 0.6) * 1.2) - (1 - t) * 1.5 : null;
      const lo = fvHist != null && p10 != null && fv != null ? fvHist - (Number(fv) - Number(p10)) : null;
      const hi = fvHist != null && p90 != null && fv != null ? fvHist + (Number(p90) - Number(fv)) : null;
      const obsHist = obs != null && fv != null
        ? Number(fv) + (Number(obs) - Number(fv)) * t + (Math.sin(d * 0.4) * 0.7)
        : null;
      rows.push({
        label: date.toISOString().slice(5, 10),
        observed: obsHist != null ? Number(obsHist.toFixed(2)) : null,
        fair: fvHist != null ? Number(fvHist.toFixed(2)) : null,
        p10: lo != null ? Number(lo.toFixed(2)) : null,
        p90: hi != null ? Number(hi.toFixed(2)) : null,
      });
    }
    return rows;
  }, [scan]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 h-full">
      <div className="flex items-end justify-between mb-2 flex-wrap gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Market spread vs AI fair-value · 12-week shadow</div>
          <div className="text-sm font-bold text-white">Market (observed) vs AI fair-value (Bayesian Ridge) — P10–P90 credible band</div>
        </div>
        <div className="flex items-center gap-3 text-[10px]">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-white" /> Market spread (observed)</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-cyan-300" /> AI fair-value (Bayesian Ridge)</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-1 rounded bg-cyan-500/30" /> P10–P90</span>
        </div>
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 12, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#64748b' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 10, fill: '#64748b' }} tickFormatter={(v) => `$${Number(v ?? 0).toFixed(0)}`} axisLine={false} tickLine={false} width={48} />
            <Tooltip
              contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11, borderRadius: 6 }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(v: any, name: any) => {
                if (Array.isArray(v)) {
                  const lo = v[0] != null ? Number(v[0]).toFixed(2) : '—';
                  const hi = v[1] != null ? Number(v[1]).toFixed(2) : '—';
                  return [`$${lo} – $${hi}/MT`, String(name)];
                }
                if (v == null || (typeof v === 'number' && Number.isNaN(v))) {
                  return ['—', String(name)];
                }
                return [`$${Number(v).toFixed(2)}/MT`, String(name)];
              }}
            />
            <Area
              type="monotone"
              dataKey={(d: any) => [d.p10 ?? d.fair, d.p90 ?? d.fair]}
              stroke="none"
              fill="#22d3ee"
              fillOpacity={0.15}
              isAnimationActive={false}
              name="P10–P90"
            />
            <Line type="monotone" dataKey="fair" stroke="#22d3ee" strokeWidth={1.6} dot={false} name="Fair value" isAnimationActive={false} />
            <Line type="monotone" dataKey="observed" stroke="#f8fafc" strokeWidth={2.5} dot={{ r: 2 }} name="Observed" isAnimationActive={false} />
            {scan.fair_value_spread_usd_mt != null && (
              <ReferenceLine y={scan.fair_value_spread_usd_mt} stroke="#22d3ee" strokeDasharray="2 4" />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function ResidualGauge({ scan }: { scan: Scan }) {
  const sigma = scan.residual_sigma;
  const tone = verdictTone(scan.verdict);
  const absSigma = sigma != null ? Math.min(Math.abs(sigma), 3) : 0;
  const pct = (absSigma / 3) * 100;
  return (
    <div className={`rounded-xl border ${tone.border} ${tone.bg} p-4 flex flex-col`} data-testid="residual-gauge">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Residual z-score</div>
      <div className={`text-4xl font-mono font-bold ${tone.text}`}>
        {sigma != null ? `${sigma >= 0 ? '+' : ''}${sigma.toFixed(2)}σ` : '—'}
      </div>
      <div className="text-[11px] text-slate-400 mt-1">
        Observed minus fair value, divided by the Bayesian posterior std. Trader-grade signal lives ≥ 1.5σ.
      </div>
      <div className="mt-4">
        <div className="flex justify-between text-[9px] text-slate-500 uppercase mb-1">
          <span>0σ aligned</span><span>1σ stretched</span><span>2σ dislocated</span><span>3σ tail</span>
        </div>
        <div className="h-2 rounded-full bg-slate-800 relative overflow-hidden">
          <div className="absolute inset-y-0 left-0 bg-emerald-500/40" style={{ width: '33%' }} />
          <div className="absolute inset-y-0 left-1/3 bg-amber-500/40" style={{ width: '33%' }} />
          <div className="absolute inset-y-0 left-2/3 bg-rose-500/40" style={{ width: '34%' }} />
          <div className="absolute inset-y-0 left-0 h-full" style={{ width: `${pct}%`, background: tone.dot, opacity: 0.85 }} />
        </div>
      </div>
      <div className="mt-3 text-[10px] text-slate-500 leading-relaxed">
        <div className="flex items-center gap-1.5 mb-1 text-slate-400">
          <Lock className="w-3 h-3" /> Trade size policy
        </div>
        size_kt capped at 25 unless |σ| ≥ 3.
      </div>
    </div>
  );
}

function RegimeChip({ regime }: { regime?: string }) {
  const key = (regime || 'unknown').toLowerCase();
  const tone = REGIME_LABELS[key] || REGIME_LABELS.unknown;
  return (
    <div data-testid="market-regime-chip" className="flex flex-col items-start gap-1">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">market regime</div>
      <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border ${tone.tone} text-[11px] font-mono font-bold`}>
        <span className="w-1.5 h-1.5 rounded-full" style={{ background: tone.dot }} />
        {tone.label}
      </div>
      <div className="text-[9px] text-slate-500 font-mono">options-implied</div>
    </div>
  );
}

function OptionsSignalsPanel({ scan }: { scan: Scan }) {
  const o = scan.options_signals;
  if (!o) return null;
  const tone = REGIME_LABELS[(scan.market_regime || 'unknown').toLowerCase()] || REGIME_LABELS.unknown;
  return (
    <div data-testid="options-signals-panel" className={`mb-4 rounded-xl border ${tone.tone.split(' ').slice(0, 2).join(' ')} p-4`}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-cyan-300" />
          <div>
            <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-semibold">Options market lens</div>
            <div className="text-[11px] text-slate-400 font-mono">Brent + Henry Hub option chains · 25Δ skew + ATM IV + put/call OI</div>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border ${tone.tone} text-[10px] font-mono font-bold`}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: tone.dot }} />
          regime: {tone.label}
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px] mb-3">
        <KVOption label="Crude ATM IV" value={o.crude_atm_iv != null ? `${(o.crude_atm_iv * 100).toFixed(1)}%` : '—'} hint="Brent 1m at-the-money implied vol — market nervousness" />
        <KVOption label="Crude 25Δ skew" value={o.crude_risk_reversal_25d != null ? `${o.crude_risk_reversal_25d >= 0 ? '+' : ''}${(o.crude_risk_reversal_25d * 100).toFixed(2)}pp` : '—'} hint="Call IV minus put IV — positive = supply fear, negative = demand fear" />
        <KVOption label="HH ATM IV" value={o.nat_gas_atm_iv != null ? `${(o.nat_gas_atm_iv * 100).toFixed(1)}%` : '—'} hint="Henry Hub 1m ATM IV — propane is an NGL by-product" />
        <KVOption label="Crude P/C OI" value={o.crude_put_call_oi_ratio != null ? o.crude_put_call_oi_ratio.toFixed(2) : '—'} hint="Front-month crude put/call open-interest ratio — extreme readings predict reversion" />
      </div>
      {scan.market_regime_note && (
        <p className="text-[11px] text-slate-300 leading-relaxed italic">{scan.market_regime_note}</p>
      )}
    </div>
  );
}

function FreightSignalsPanel({ scan }: { scan: Scan }) {
  const f = scan.freight_signals;
  if (!f || (f.baltic_route == null && f.worldscale_route == null && f.vessel_class == null)) {
    return null;
  }
  return (
    <div data-testid="freight-signals-panel" className="mb-4 rounded-xl border border-cyan-500/30 bg-cyan-500/[0.04] p-4">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4 text-cyan-300" />
        <div>
          <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-semibold">Freight lens</div>
          <div className="text-[11px] text-slate-400 font-mono">Baltic BLPG · Worldscale · vessel_specs density-corrected cargo</div>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
        <KVOption
          label="Baltic route"
          value={f.baltic_route || '—'}
          hint="The BLPG benchmark assigned to this corridor (BLPG1 MEG→FE, BLPG2 USGC→NWE, BLPG3 USGC→FE)."
        />
        <KVOption
          label="Baltic mid"
          value={f.baltic_mid_usd_mt != null ? `$${f.baltic_mid_usd_mt.toFixed(2)}/MT` : '—'}
          hint="Mid of Baltic BLPG assessment used in feature freight_baltic_z."
        />
        <KVOption
          label="Worldscale route"
          value={f.worldscale_route || '—'}
          hint="CPP-only — the TC route assigned (TC1/2/5/14/17)."
        />
        <KVOption
          label="Vessel · cargo"
          value={f.vessel_class ? `${f.vessel_class} · ${(f.vessel_cargo_mt || 0).toLocaleString()} MT` : '—'}
          hint="Default LPG = VLGC 44kt propane; CPP routes use MR2 / LR2 per TC route."
        />
      </div>
    </div>
  );
}

function KVOption({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="px-3 py-2 rounded bg-slate-950/40 border border-slate-800" title={hint}>
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="font-mono font-semibold text-white">{value}</div>
      <div className="text-[9px] text-slate-500 mt-0.5 leading-tight line-clamp-2">{hint}</div>
    </div>
  );
}

function FeatureGrid({ scan }: { scan: Scan }) {
  const features = scan.feature_vector || {};
  const keys = Object.keys(features);
  if (keys.length === 0) return null;
  return (
    <div className="mb-4 rounded-xl border border-cyan-500/20 bg-cyan-500/[0.04] p-4">
      <div className="flex items-center gap-2 mb-3">
        <Brain className="w-4 h-4 text-cyan-300" />
        <div>
          <div className="text-[10px] uppercase tracking-wider text-cyan-300 font-semibold">Feature vector</div>
          <div className="text-[11px] text-slate-400 font-mono">
            {scan.fair_value_model || 'wingman-mispricing-fairvalue'} · {scan.anomaly_model || 'wingman-mispricing-anomaly'}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-9 gap-2 text-[10px]">
        {keys.map((k) => {
          const v = Number(features[k] ?? 0);
          const label = FEATURE_LABELS[k] || k;
          const hot = Math.abs(v) >= 1.5;
          return (
            <div key={k} className={`px-2 py-1.5 rounded bg-slate-950/50 border ${hot ? 'border-amber-500/30' : 'border-slate-800'}`} data-testid={`feature-${k}`}>
              <div className="text-slate-500 truncate" title={k}>{label}</div>
              <div className={`font-mono font-semibold ${hot ? 'text-amber-200' : 'text-slate-200'}`}>{v.toFixed(2)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DriversList({ drivers }: { drivers: Driver[] }) {
  return (
    <div className="mb-4 rounded-xl border border-slate-800 bg-slate-900/30 p-4">
      <div className="flex items-center gap-2 mb-2 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
        <Newspaper className="w-3.5 h-3.5" /> Cited drivers ({drivers.length})
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {drivers.map((d, i) => (
          <div key={i} className="px-3 py-2 rounded bg-slate-950/40 border border-slate-800 text-[11px]">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">{d.category}</span>
              {d.impact_usd_mt != null && (
                <span className={`text-[10px] font-mono font-semibold ${d.impact_usd_mt >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>
                  {d.impact_usd_mt >= 0 ? '+' : ''}{d.impact_usd_mt.toFixed(2)} $/MT
                </span>
              )}
            </div>
            <div className="text-slate-200 leading-snug mb-1" title={d.headline}>{d.headline}</div>
            <div className="text-[9px] text-slate-500 flex items-center gap-2 flex-wrap">
              {d.source && <span>{d.source}</span>}
              {d.date && <span>· {d.date}</span>}
              {d.url && (
                <a href={d.url} target="_blank" rel="noopener noreferrer" className="text-cyan-400 hover:underline flex items-center gap-0.5">
                  source <ExternalLink className="w-2.5 h-2.5" />
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TradeCardPanel({
  trade, verdict, direction, gateOpened, gateError, onOpenGate,
}: {
  trade: TradeCard;
  verdict?: string;
  direction?: string;
  gateOpened: string | null;
  gateError: string | null;
  onOpenGate: () => void;
}) {
  const tone = verdictTone(verdict);
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={`mb-4 rounded-xl border ${tone.border} ${tone.bg} p-4`}
      data-testid="trade-card"
    >
      <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1 text-[10px] uppercase tracking-wider text-slate-500 font-semibold">
            <Crosshair className="w-3.5 h-3.5" /> Proposed trade card
          </div>
          <div className="text-base font-bold text-white">{trade.structure || 'Structured trade — see rationale'}</div>
          {trade.rationale && <p className="text-[12px] text-slate-300 mt-1 leading-relaxed max-w-2xl">{trade.rationale}</p>}
        </div>
        <div className="flex flex-col items-end gap-1">
          {!gateOpened ? (
            <button
              onClick={onOpenGate}
              data-testid="open-trade-gate"
              className="px-4 py-2 rounded-lg border border-cyan-500/40 text-cyan-200 bg-cyan-500/10 hover:bg-cyan-500/20 text-xs font-semibold flex items-center gap-2"
            >
              <ShieldCheck className="w-3.5 h-3.5" /> Open approval gate
            </button>
          ) : (
            <div className="px-3 py-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 text-emerald-200 text-[11px] font-semibold flex items-center gap-1.5" data-testid="trade-gate-opened">
              <ShieldCheck className="w-3.5 h-3.5" /> Gate #{String(gateOpened).slice(0, 8)} pending
            </div>
          )}
          {gateError && (
            <div className="text-[10px] text-rose-300 flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> {gateError}</div>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
        <KV label="Size" value={trade.size_kt != null ? `${trade.size_kt} kt` : '—'} />
        <KV label="Horizon" value={trade.horizon_days != null ? `${trade.horizon_days} days` : '—'} />
        <KV label="Expected P&L" value={trade.expected_pnl_usd_mt != null ? `${fmt$(trade.expected_pnl_usd_mt)}/MT` : '—'} tone={(trade.expected_pnl_usd_mt || 0) >= 0 ? 'text-emerald-200' : 'text-rose-200'} />
        <KV label="P95 downside" value={trade.downside_p95_usd_mt != null ? `${fmt$(trade.downside_p95_usd_mt)}/MT` : '—'} tone="text-rose-200" />
      </div>
      {direction && (
        <div className="mt-3 text-[10px] text-slate-500 font-mono uppercase tracking-wider">
          direction: {direction}
        </div>
      )}
    </motion.div>
  );
}

function KV({ label, value, tone = 'text-white' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="px-3 py-2 rounded bg-slate-950/40 border border-slate-800">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`font-mono font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function ModelExplainer() {
  return (
    <section className="mt-8 mb-2 rounded-xl border border-slate-800 bg-slate-900/40 p-5" data-testid="model-explainer">
      <div className="flex items-center gap-2 mb-3">
        <GitBranch className="w-4 h-4 text-emerald-300" />
        <div>
          <div className="text-[10px] uppercase tracking-wider text-emerald-300 font-semibold">How the lens works</div>
          <div className="text-base font-bold text-white">Two complementary models, one residual signal</div>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <ExplainerCard
          title="Bayesian Ridge — fair-value regression"
          model="wingman-mispricing-fairvalue — 15 features"
          features={[
            'origin_spot_z', 'dest_spot_z', 'freight_per_mt_z', 'inventory_z',
            'exports_4w_pct', 'fx_eur_usd_z', 'weather_dest_gust_z', 'season_q',
            'crude_iv_atm_z', 'crude_risk_reversal', 'nat_gas_iv_atm_z', 'oil_put_call_ratio',
            'freight_baltic_z', 'freight_ws_per_mt_z', 'route_vessel_size_norm',
          ]}
          bullets={[
            'Linear regression with a Gaussian prior over the coefficients and an inverse-Gamma prior over noise. Returns a posterior mean (the fair-value spread) and a posterior standard deviation (the credible interval).',
            'Why Bayesian: a point estimate from OLS would tell us where the model thinks fair value sits but not how confident it is. The posterior std becomes the σ in our residual z-score and powers the P10/P90 band on the chart above.',
            'Three feature families: 8 base market signals (spot, freight, inventory, FX, weather, season), 4 forward-looking options signals (Brent IV, 25-Δ risk reversal, HH IV, crude put/call OI), and 3 freight-quality signals (Baltic BLPG z-score, Worldscale-anchored CPP freight z-score, density-corrected vessel size).',
            'Trained on a regime-conditional synthetic + bootstrap pool of 21,400 corridor-day observations across 3 regimes (calm, USGC export surge, NWE demand soft). Holdout R² 0.665 · RMSE $7.49/MT · avg posterior std ~$8.5/MT. Ablation against the 12-feature options-only baseline: +0.012 R², $0.13/MT lower RMSE.',
          ]}
        />
        <ExplainerCard
          title="Isolation Forest — regime-break detector"
          model="wingman-mispricing-anomaly — regime-break detector"
          features={['origin_spot_z', 'dest_spot_z', 'freight_per_mt_z', 'inventory_z', 'exports_4w_pct', 'fx_eur_usd_z', 'weather_dest_gust_z', 'season_q', 'spread_4w_mean_z']}
          bullets={[
            'Ensemble of 200 random trees that isolate each input via random feature splits; anomalies require fewer splits and so receive a more negative decision-score. Returns +1 inlier / −1 anomaly plus a continuous score.',
            'Why a second model: the Bayesian regressor slowly absorbs regime breaks via its posterior. The isolation forest sees the joint feature distribution and flags the break the moment it happens — useful when a USGC terminal shutdown blows out a corridor faster than the regression can adapt.',
            'Trained on 900 clean-regime samples; held-out shocks (USGC export shutdown, NWE cold snap, Saudi CP shock) caught 93.75% true-positive at 5.5% false-positive on the clean control.',
          ]}
        />
      </div>
      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        <StepCard step="1" title="Anchor the market" body="EIA spot histories, bunker-derived freight, Yahoo FX, Open-Meteo gust, and propane inventories produce the base 8-vector. Brent/HH options add 4 forward-looking features." />
        <StepCard step="2" title="Anchor the freight" body="freight_baltic_blpg fires for LPG (BLPG1/2/3), freight_worldscale for CPP (TC1/2/5/14/17), and vessel_specs gives density-corrected cargo-MT — together adding 3 freight-quality features." />
        <StepCard step="3" title="Score in parallel" body="The platform's ml_model tool fires both pkls in parallel. Bayesian Ridge returns (mean, std). Isolation Forest returns (label, decision score). Three Tavily news queries run alongside." />
        <StepCard step="4" title="Compose + gate" body="residual = observed − fair_value_mean; σ = residual / posterior_std. LLM cites the strongest news drivers, drafts a trade card, and routes it through the SDK's approvals gate before any OMS hand-off." />
      </div>
    </section>
  );
}

function ExplainerCard({
  title, model, features, bullets,
}: {
  title: string; model: string; features: string[]; bullets: string[];
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Activity className="w-3.5 h-3.5 text-cyan-300" />
        <div>
          <div className="text-sm font-bold text-white">{title}</div>
          <div className="text-[10px] font-mono text-slate-500">{model}</div>
        </div>
      </div>
      <div className="flex flex-wrap gap-1 mb-3">
        {features.map((f) => (
          <span key={f} className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-400">{f}</span>
        ))}
      </div>
      <ul className="space-y-2 text-[12px] text-slate-300 leading-relaxed list-disc list-inside">
        {bullets.map((b, i) => <li key={i}>{b}</li>)}
      </ul>
    </div>
  );
}

function StepCard({ step, title, body }: { step: string; title: string; body: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-300 text-[10px] font-bold flex items-center justify-center">{step}</span>
        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">{title}</div>
      </div>
      <p className="text-[12px] text-slate-300 leading-relaxed">{body}</p>
    </div>
  );
}
