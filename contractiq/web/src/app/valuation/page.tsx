'use client';


import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  LineChart as LineChartIcon, TrendingUp, Gauge, Loader2, RefreshCw,
  ArrowRight, AlertTriangle, DollarSign, Activity, Sparkles, X,
  ExternalLink, ChevronLeft,
} from 'lucide-react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Area,
  AreaChart, CartesianGrid,
} from 'recharts';

import { apiFetch } from '@/lib/api';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

// ── Types ──────────────────────────────────────────────────────────────

type CurvePoint = {
  tenor_months: number;
  date?: string;
  price: number;
  confidence_low?: number;
  confidence_high?: number;
  data_quality?: string;
};

type ForecastCurve = {
  id: string;
  market: string;
  methodology: string;
  unit: string;
  base_date: string;
  tenor_months: number;
  curve: CurvePoint[];
  fundamental_drivers?: string[];
  sentiment_score?: number;
  sentiment_adjustment_pct?: number;
  narrative?: string;
  data_sources?: string[];
  status: string;
  cost_usd?: number;
  duration_ms?: number;
  error_message?: string;
  created_at: string;
};

type Valuation = {
  id: string;
  valuation_type: string;
  scope: string;
  contract_id?: string | null;
  valuation_date?: string;
  payload?: any;
  portfolio_mtm?: number;
  portfolio_mtm_ccy?: string;
  total_shortfall_usd?: number;
  alert_count?: number;
  status: string;
  cost_usd?: number;
  duration_ms?: number;
  error_message?: string;
  created_at: string;
};

// ── Helpers ────────────────────────────────────────────────────────────

function fmtMoney(n: number | null | undefined, ccy = 'USD'): string {
  if (n == null) return '—';
  const sign = n < 0 ? '-' : '';
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${sign}${ccy} ${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${ccy} ${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${ccy} ${(abs / 1e3).toFixed(0)}K`;
  return `${sign}${ccy} ${abs.toFixed(0)}`;
}

function severityColor(s: string): string {
  switch ((s || '').toLowerCase()) {
    case 'critical': return 'bg-rose-500/10 text-rose-300 border-rose-500/40';
    case 'high':     return 'bg-orange-500/10 text-orange-300 border-orange-500/40';
    case 'medium':   return 'bg-amber-500/10 text-amber-300 border-amber-500/40';
    default:         return 'bg-slate-500/10 text-slate-300 border-slate-500/40';
  }
}

// ── Page ───────────────────────────────────────────────────────────────

export default function ValuationPage() {
  const [curves, setCurves] = useState<ForecastCurve[]>([]);
  const [valuation, setValuation] = useState<Valuation | null>(null);
  const [topMonitor, setTopMonitor] = useState<Valuation | null>(null);
  const [loading, setLoading] = useState(true);
  const [runningCurves, setRunningCurves] = useState(false);
  const [runningVal, setRunningVal] = useState(false);
  const [runningTop, setRunningTop] = useState(false);
  const [selectedCurve, setSelectedCurve] = useState<ForecastCurve | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) { setLoading(false); return; }
    try {
      const [cRes, vRes, tRes] = await Promise.all([
        fetch(`${API_URL}/api/contractiq/insights/valuation/forecast-curves`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/contractiq/insights/valuation/latest`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/api/contractiq/insights/valuation/top-monitor`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      const cj = await cRes.json();
      const vj = await vRes.json();
      const tj = await tRes.json();
      setCurves(cj.data?.curves || []);
      setValuation(vj.data || null);
      setTopMonitor(tj.data || null);
    } catch (e: any) {
      setError(e?.message || 'Failed to load');
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const runCurves = async () => {
    setError(null);
    setRunningCurves(true);
    const token = getToken();
    const r = await apiFetch(`${API_URL}/api/contractiq/insights/valuation/forecast-curves/run`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ tenor_months: 24, methodology: 'market+sentiment' }),
    });
    if (!r.ok) setError(r.error || 'Forecast run failed');
    await load();
    setRunningCurves(false);
  };

  const runValuation = async () => {
    setError(null);
    setRunningVal(true);
    const token = getToken();
    const r = await apiFetch(`${API_URL}/api/contractiq/insights/valuation/run`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: 'portfolio' }),
    });
    if (!r.ok) setError(r.error || 'Valuation run failed');
    await load();
    setRunningVal(false);
  };

  const runTop = async () => {
    setError(null);
    setRunningTop(true);
    const token = getToken();
    const r = await apiFetch(`${API_URL}/api/contractiq/insights/valuation/top-monitor/run`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!r.ok) setError(r.error || 'Top monitor run failed');
    await load();
    setRunningTop(false);
  };

  const runAll = async () => {
    setError(null);
    await runCurves();
    await runValuation();
    await runTop();
  };

  const kpis = useMemo(() => {
    const perContract = valuation?.payload?.per_contract || [];
    const bigPositions = perContract.filter((p: any) => Math.abs(p?.mtm || 0) > 5_000_000).length;
    const alerts = topMonitor?.payload?.alerts || [];
    return {
      portfolio_mtm: valuation?.portfolio_mtm ?? null,
      ccy: valuation?.portfolio_mtm_ccy || 'USD',
      positions: perContract.length,
      big_positions: bigPositions,
      top_alerts: alerts.length,
      shortfall: topMonitor?.total_shortfall_usd ?? null,
      curves: curves.length,
    };
  }, [valuation, topMonitor, curves]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-indigo-400 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-400 mb-2">
            <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
          </a>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-violet-600/20 border border-indigo-500/30 flex items-center justify-center">
                <LineChartIcon className="w-6 h-6 text-indigo-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">Portfolio Valuation &amp; Forecast</h1>
                <p className="text-xs text-slate-400">
                  Forward curves · Mark-to-Market · Take-or-Pay monitoring — all driven by
                  <code className="text-indigo-300"> contractiq-price-forecaster</code>,
                  <code className="text-indigo-300"> contractiq-portfolio-valuator</code>, and
                  <code className="text-indigo-300"> contractiq-top-monitor</code>.
                </p>
              </div>
            </div>
            <button
              onClick={runAll}
              disabled={runningCurves || runningVal || runningTop}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-violet-600 text-white text-xs font-semibold disabled:opacity-50 hover:shadow-lg hover:shadow-indigo-500/25 transition-all"
            >
              {(runningCurves || runningVal || runningTop)
                ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                : <RefreshCw className="w-3.5 h-3.5" />}
              Refresh Valuation
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-rose-500/10 border border-rose-500/30 rounded-lg px-4 py-2 text-xs text-rose-300">
            {error}
          </div>
        )}

        {/* KPI strip */}
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: 'Portfolio MtM', value: fmtMoney(kpis.portfolio_mtm, kpis.ccy), icon: DollarSign, color: kpis.portfolio_mtm != null && kpis.portfolio_mtm < 0 ? 'text-rose-400' : 'text-emerald-400' },
            { label: 'Positions', value: kpis.positions, icon: Activity, color: 'text-cyan-400' },
            { label: 'Positions > $5M', value: kpis.big_positions, icon: TrendingUp, color: 'text-amber-400' },
            { label: 'T-o-P Alerts', value: kpis.top_alerts, icon: AlertTriangle, color: kpis.top_alerts > 0 ? 'text-rose-400' : 'text-slate-400' },
            { label: 'Forward Curves', value: kpis.curves, icon: LineChartIcon, color: 'text-indigo-400' },
          ].map(k => (
            <div key={k.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <k.icon className={`w-4 h-4 ${k.color}`} />
                <span className="text-[10px] uppercase tracking-wider text-slate-500">{k.label}</span>
              </div>
              <p className={`text-2xl font-bold ${k.color}`}>{k.value}</p>
            </div>
          ))}
        </div>

        {/* ── Forward curves panel ───────────────────────────────── */}
        <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5" data-testid="curves-panel">
          <header className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <LineChartIcon className="w-4 h-4 text-indigo-400" /> Forward Curves
              </h2>
              <p className="text-[11px] text-slate-500 mt-0.5">
                Auto-picked markets based on the clusters in your portfolio. Click any curve for the narrative + drivers.
              </p>
            </div>
            <button
              onClick={runCurves}
              disabled={runningCurves}
              className="text-xs px-3 py-1.5 rounded-lg bg-indigo-500/15 border border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/25 disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {runningCurves ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              Run Forecaster
            </button>
          </header>

          {curves.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-xs text-slate-500 mb-3">No forward curves yet.</p>
              <button
                onClick={runCurves}
                disabled={runningCurves}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-500/20 border border-indigo-500/40 text-indigo-300 text-xs disabled:opacity-50"
              >
                {runningCurves && <Loader2 className="w-3 h-3 animate-spin" />}
                Generate Forward Curves
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-3">
              {curves.map(c => (
                <button
                  key={c.id}
                  onClick={() => setSelectedCurve(c)}
                  className="text-left bg-slate-900/40 border border-slate-700/50 rounded-lg p-3 hover:border-indigo-500/50 transition"
                >
                  <div className="flex items-center justify-between mb-1">
                    <p className="text-xs font-semibold text-white truncate">{c.market}</p>
                    <span className="text-[9px] uppercase text-slate-500">{c.unit}</span>
                  </div>
                  <div className="h-20 -mx-2">
                    {Array.isArray(c.curve) && c.curve.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={c.curve}>
                          <defs>
                            <linearGradient id={`g-${c.id}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                              <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <Area
                            type="monotone"
                            dataKey="price"
                            stroke="#818cf8"
                            strokeWidth={1.5}
                            fill={`url(#g-${c.id})`}
                            dot={false}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-[10px] text-slate-600 italic">
                        no data
                      </div>
                    )}
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-500 mt-1">
                    <span>{c.tenor_months}m tenor</span>
                    {c.sentiment_score != null && (
                      <span className={c.sentiment_score >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                        sent {c.sentiment_score.toFixed(2)}
                      </span>
                    )}
                  </div>
                  {c.status === 'failed' && (
                    <p className="text-[10px] text-rose-400 mt-1 truncate" title={c.error_message || ''}>
                      failed · {c.error_message?.slice(0, 40)}
                    </p>
                  )}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* ── Portfolio valuation ───────────────────────────────── */}
        <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5" data-testid="valuation-panel">
          <header className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-400" /> Portfolio Mark-to-Market
              </h2>
              <p className="text-[11px] text-slate-500 mt-0.5">
                {valuation?.valuation_date
                  ? `As of ${new Date(valuation.valuation_date).toLocaleDateString()}`
                  : 'No valuation has been run yet.'}
              </p>
            </div>
            <button
              onClick={runValuation}
              disabled={runningVal}
              className="text-xs px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {runningVal ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              Run Valuator
            </button>
          </header>

          {valuation?.status === 'completed' && valuation.payload ? (
            <ValuationBody valuation={valuation} />
          ) : valuation?.status === 'failed' ? (
            <p className="text-xs text-rose-300 italic">Failed: {valuation.error_message}</p>
          ) : (
            <p className="text-xs text-slate-500 italic">Click "Run Valuator" to mark the portfolio to market.</p>
          )}
        </section>

        {/* ── Take-or-Pay monitor ───────────────────────────────── */}
        <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5" data-testid="top-monitor-panel">
          <header className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold text-white flex items-center gap-2">
                <Gauge className="w-4 h-4 text-amber-400" /> Take-or-Pay Monitor
              </h2>
              <p className="text-[11px] text-slate-500 mt-0.5">
                Projects year-end lifted volumes, flags shortfalls against T-o-P / ACQ / UIOSI thresholds.
              </p>
            </div>
            <button
              onClick={runTop}
              disabled={runningTop}
              className="text-xs px-3 py-1.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-amber-300 hover:bg-amber-500/25 disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {runningTop ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
              Run Monitor
            </button>
          </header>

          {topMonitor?.status === 'completed' && topMonitor.payload ? (
            <TopMonitorBody monitor={topMonitor} />
          ) : topMonitor?.status === 'failed' ? (
            <p className="text-xs text-rose-300 italic">Failed: {topMonitor.error_message}</p>
          ) : (
            <p className="text-xs text-slate-500 italic">Click "Run Monitor" to scan for Take-or-Pay shortfall.</p>
          )}
        </section>

        {selectedCurve && (
          <CurveModal curve={selectedCurve} onClose={() => setSelectedCurve(null)} />
        )}
      </div>
    </div>
  );
}

// ── Valuation body ─────────────────────────────────────────────────────

function ValuationBody({ valuation }: { valuation: Valuation }) {
  const p = valuation.payload || {};
  const perContract: any[] = p.per_contract || [];
  const clusterTotals: Record<string, number> = p.cluster_type_totals || {};
  const topRisks: any[] = p.top_risks || [];
  const greeks = p.greeks || {};
  const ccy = p.portfolio_mtm_ccy || valuation.portfolio_mtm_ccy || 'USD';

  return (
    <div className="space-y-5">
      {/* Greeks */}
      {Object.keys(greeks).length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Portfolio Greeks</p>
          <div className="grid grid-cols-3 gap-2">
            {Object.entries(greeks).map(([k, v]: [string, any]) => (
              <div key={k} className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
                <p className="text-[10px] text-slate-500">{k.replace(/_/g, ' ')}</p>
                <p className="text-sm font-semibold text-white tabular-nums">{fmtMoney(v, '')}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per contract */}
      {perContract.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Per-Contract MtM</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="per-contract-table">
              <thead>
                <tr className="text-left text-[10px] uppercase text-slate-500 border-b border-slate-700/50">
                  <th className="py-2 pl-2">Contract</th>
                  <th className="py-2">MtM</th>
                  <th className="py-2">Cluster Breakdown</th>
                  <th className="py-2 pr-2"></th>
                </tr>
              </thead>
              <tbody>
                {perContract.map((c: any, i: number) => (
                  <tr key={i} className="border-b border-slate-800/40 hover:bg-slate-800/20">
                    <td className="py-2 pl-2 text-white font-medium">{c.title || c.contract_id?.slice(0, 8)}</td>
                    <td className={`py-2 tabular-nums ${(c.mtm || 0) < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                      {fmtMoney(c.mtm, c.currency || ccy)}
                    </td>
                    <td className="py-2 text-slate-400">
                      {(c.cluster_breakdown || []).map((cb: any, j: number) => (
                        <span key={j} className="inline-block mr-2 text-[10px]">
                          {cb.cluster_key}: <span className={(cb.mtm || 0) < 0 ? 'text-rose-400' : 'text-emerald-400'}>{fmtMoney(cb.mtm, '')}</span>
                        </span>
                      ))}
                    </td>
                    <td className="py-2 pr-2">
                      {c.contract_id && (
                        <a href={`/contracts/${c.contract_id}`} className="text-indigo-400 hover:text-indigo-300" title="Open contract">
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cluster type totals */}
      {Object.keys(clusterTotals).length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">By Cluster Type</p>
          <div className="grid grid-cols-4 gap-2">
            {Object.entries(clusterTotals).map(([k, v]) => (
              <div key={k} className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
                <p className="text-[10px] text-slate-500">{k.replace(/_/g, ' ')}</p>
                <p className={`text-sm font-semibold tabular-nums ${(v || 0) < 0 ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {fmtMoney(v, ccy)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top risks */}
      {topRisks.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Top Risks</p>
          <div className="space-y-2">
            {topRisks.map((r: any, i: number) => (
              <div key={i} className={`border rounded-lg px-3 py-2 flex items-start gap-2 ${severityColor(r.severity)}`}>
                <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium">{r.title}</p>
                  {r.mtm_impact != null && (
                    <p className="text-[10px] opacity-75">impact: {fmtMoney(r.mtm_impact, ccy)}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Narrative */}
      {p.narrative && (
        <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
          <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Narrative</p>
          <p className="text-xs text-slate-300 leading-relaxed">{p.narrative}</p>
        </div>
      )}
    </div>
  );
}

// ── Take-or-Pay body ───────────────────────────────────────────────────

function TopMonitorBody({ monitor }: { monitor: Valuation }) {
  const p = monitor.payload || {};
  const alerts: any[] = p.alerts || [];

  if (alerts.length === 0) {
    return <p className="text-xs text-emerald-300 italic">All contracts on track — no Take-or-Pay shortfall projected.</p>;
  }

  return (
    <div className="space-y-2" data-testid="top-alerts">
      {alerts.map((a: any, i: number) => (
        <div key={i} className={`border rounded-lg p-3 ${severityColor(a.severity)}`}>
          <div className="flex items-start justify-between gap-3">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-white">{a.title}</p>
              <p className="text-[10px] mt-0.5 opacity-75">{a.metric} · {a.acq_unit || ''}</p>
            </div>
            <span className="text-[10px] uppercase">{a.severity}</span>
          </div>
          <div className="grid grid-cols-4 gap-2 mt-2 text-[11px]">
            {[
              { label: 'ACQ',         v: a.acq?.toLocaleString() },
              { label: 'YTD lifted',  v: a.lifted_to_date?.toLocaleString() },
              { label: 'Proj YE',     v: a.projected_year_end?.toLocaleString() },
              { label: 'Threshold',   v: a.threshold?.toLocaleString() },
            ].map(x => (
              <div key={x.label}>
                <p className="text-slate-500 text-[9px] uppercase">{x.label}</p>
                <p className="text-white">{x.v || '—'}</p>
              </div>
            ))}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-700/40">
            <p className="text-[11px] text-white/90">
              Shortfall: <span className="font-semibold">{a.shortfall_units?.toLocaleString() || 0}</span> units
              {a.shortfall_usd != null && <> · <span className="font-semibold">{fmtMoney(a.shortfall_usd)}</span></>}
            </p>
            {a.recommendation && (
              <p className="text-[11px] mt-1 opacity-90">{a.recommendation}</p>
            )}
          </div>
        </div>
      ))}
      {p.narrative && (
        <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
          <p className="text-xs text-slate-300 leading-relaxed">{p.narrative}</p>
        </div>
      )}
    </div>
  );
}

// ── Curve detail modal ─────────────────────────────────────────────────

function CurveModal({ curve, onClose }: { curve: ForecastCurve; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        onClick={e => e.stopPropagation()}
        className="bg-[#0B0F19] border border-slate-700/60 rounded-2xl max-w-3xl w-full max-h-[85vh] flex flex-col shadow-2xl"
      >
        <header className="flex items-center justify-between p-5 border-b border-slate-700/50">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Forward Curve</p>
            <h2 className="text-base font-semibold text-white">{curve.market}</h2>
            <p className="text-xs text-slate-500 mt-1">
              {curve.methodology} · base {new Date(curve.base_date).toLocaleDateString()} · {curve.unit}
            </p>
          </div>
          <button onClick={onClose} className="p-2 rounded-lg text-slate-400 hover:bg-slate-800/60 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div className="h-60 bg-slate-900/40 border border-slate-700/40 rounded-lg p-2">
            {Array.isArray(curve.curve) && curve.curve.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={curve.curve}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                <XAxis dataKey="tenor_months" tick={{ fill: '#64748b', fontSize: 10 }} />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }} domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', fontSize: 11 }}
                  labelStyle={{ color: '#818cf8' }}
                />
                <Line type="monotone" dataKey="confidence_high" stroke="#4338ca" strokeWidth={1} strokeDasharray="3 3" dot={false} />
                <Line type="monotone" dataKey="price" stroke="#818cf8" strokeWidth={2} dot={{ r: 2 }} />
                <Line type="monotone" dataKey="confidence_low" stroke="#4338ca" strokeWidth={1} strokeDasharray="3 3" dot={false} />
              </LineChart>
            </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-slate-500 italic">No curve data available</div>
            )}
          </div>

          {curve.narrative && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Narrative</p>
              <p className="text-xs text-slate-300 leading-relaxed">{curve.narrative}</p>
            </div>
          )}

          {curve.fundamental_drivers && curve.fundamental_drivers.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Fundamental drivers</p>
              <ul className="text-xs text-slate-300 list-disc list-inside space-y-0.5">
                {curve.fundamental_drivers.map((d, i) => <li key={i}>{d}</li>)}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2 text-[11px]">
            {curve.sentiment_score != null && (
              <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
                <p className="text-[10px] text-slate-500">Sentiment</p>
                <p className={`text-sm font-semibold ${curve.sentiment_score >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {curve.sentiment_score.toFixed(2)}
                </p>
              </div>
            )}
            {curve.sentiment_adjustment_pct != null && (
              <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
                <p className="text-[10px] text-slate-500">Sentiment adj</p>
                <p className="text-sm font-semibold text-white">{curve.sentiment_adjustment_pct.toFixed(2)}%</p>
              </div>
            )}
            {curve.duration_ms != null && (
              <div className="bg-slate-900/40 border border-slate-700/50 rounded-lg px-3 py-2">
                <p className="text-[10px] text-slate-500">Run time</p>
                <p className="text-sm font-semibold text-white">{(curve.duration_ms / 1000).toFixed(1)}s</p>
              </div>
            )}
          </div>

          {curve.data_sources && curve.data_sources.length > 0 && (
            <p className="text-[10px] text-slate-500">
              Sources: {curve.data_sources.join(' · ')}
            </p>
          )}
        </div>
      </motion.div>
    </div>
  );
}
