'use client';

import { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import {
  Activity, TrendingUp, TrendingDown, AlertTriangle, RefreshCw,
  DollarSign, Zap, Flame, ArrowUpRight, ArrowDownRight, Check,
  Sparkles, Loader2,
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  AreaChart, Area, CartesianGrid,
} from 'recharts';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }

const POLL_INTERVAL = 15_000;

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (<div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
    <p className="text-xs text-slate-400 mb-1">{label}</p>
    {payload.map((p: any, i: number) => (<p key={i} className="text-xs font-medium" style={{ color: p.color }}>{p.name}: {typeof p.value === 'number' ? p.value.toLocaleString() : p.value}</p>))}
  </div>);
};

function formatCurrency(v: number): string {
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

function extractCarbonHeadline(content?: string): string | null {
  if (!content) return null;
  const m = content.match(/Average:\s*([0-9]+(?:\.[0-9]+)?)\s*([^\n]+)/);
  if (m) return `${parseFloat(m[1]).toFixed(0)} ${m[2].trim()}`;
  return null;
}

interface MarketData {
  timestamp: string;
  market: {
    power: { available: boolean; content: string; metadata?: { average?: number; min?: number; max?: number; unit?: string; point_count?: number } };
    carbon: { available: boolean; content: string; metadata?: { records?: number; unit?: string } };
    fx: { available: boolean; content: string; metadata?: { pair?: string; latest_rate?: number; latest_date?: string; period_change_pct?: number } };
  };
  exposure: {
    contracts: {
      id: string; title: string; contract_type: string;
      contract_price: number | null; spot_price: number;
      pnl_per_mwh: number; annual_pnl: number; mark_to_market: number;
      capacity_mw: number; remaining_years: number;
      risk_score: number | null; direction: string;
    }[];
    totals: { total_annual_pnl: number; total_mtm: number; contracts_in_money: number; contracts_out_of_money: number };
  };
  recent_alerts: { id: string; severity: string; title: string; description: string; alert_type: string; delta_pct: number | null; is_acknowledged: boolean; created_at: string }[];
}

export default function MarketPage() {
  const [data, setData] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [pollActive, setPollActive] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = async () => {
    try {
      const token = getToken();
      if (!token) return;
      const res = await fetch(`${API_URL}/api/contractiq/market-data`, { headers: { Authorization: `Bearer ${token}` } });
      const body = await res.json();
      if (body.data) { setData(body.data); setLastUpdate(new Date()); }
    } catch { /* silent */ }
    setLoading(false);
  };

  const acknowledgeAlert = async (alertId: string) => {
    const token = getToken();
    await fetch(`${API_URL}/api/contractiq/alerts/${alertId}/acknowledge`, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` },
    });
    fetchData();
  };

  const runMarketMonitor = async () => {
    setRunning(true);
    setRunMessage('');
    const token = getToken();
    try {
      const res = await fetch(`${API_URL}/api/contractiq/insights/market-monitor/run`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const body = await res.json();
      if (body.data) {
        setRunMessage(`Monitor run complete. Cost $${(body.data.cost_usd || 0).toFixed(3)}, took ${Math.round((body.data.duration_ms || 0) / 1000)}s.`);
      } else {
        setRunMessage(`Monitor failed: ${body.error?.message || 'unknown error'}`);
      }
      // Refresh alerts
      await fetchData();
    } catch (e: any) {
      setRunMessage(`Monitor failed: ${e?.message || 'network error'}`);
    }
    setRunning(false);
    // Clear message after 8s
    setTimeout(() => setRunMessage(''), 8000);
  };

  useEffect(() => {
    fetchData();
    if (pollActive) {
      intervalRef.current = setInterval(fetchData, POLL_INTERVAL);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [pollActive]);

  const d = data;
  const contracts = d?.exposure?.contracts || [];
  const totals = d?.exposure?.totals;
  const alerts = d?.recent_alerts || [];

  // Chart data
  const pnlData = contracts
    .filter(c => c.contract_price != null)
    .sort((a, b) => b.annual_pnl - a.annual_pnl)
    .map(c => ({ name: c.title.length > 18 ? c.title.slice(0, 18) + '...' : c.title, pnl: c.annual_pnl, mtm: c.mark_to_market }));

  const mtmData = contracts
    .filter(c => c.mark_to_market !== 0)
    .sort((a, b) => Math.abs(b.mark_to_market) - Math.abs(a.mark_to_market))
    .map(c => ({ name: c.title.length > 18 ? c.title.slice(0, 18) + '...' : c.title, mtm: c.mark_to_market }));

  return (
    <div className="p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2"><Activity className="w-5 h-5 text-emerald-400" /> Market & Risk Monitor</h1>
            <p className="text-sm text-slate-400 mt-1">Live market data, portfolio PnL, and risk exposure</p>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdate && <span className="text-[10px] text-slate-500">Updated {lastUpdate.toLocaleTimeString()}</span>}
            <button onClick={() => setPollActive(!pollActive)}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors ${pollActive ? 'border-emerald-500/30 text-emerald-400 bg-emerald-500/5' : 'border-slate-700 text-slate-400'}`}>
              <RefreshCw className={`w-3 h-3 ${pollActive ? 'animate-spin' : ''}`} style={{ animationDuration: '3s' }} />
              {pollActive ? 'Live' : 'Paused'}
            </button>
            <button onClick={runMarketMonitor} disabled={running}
              title="Run the Abenix market monitor pipeline to generate fresh alerts"
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white font-semibold hover:shadow-lg hover:shadow-emerald-500/25 disabled:opacity-60 transition-all">
              {running ? <><Loader2 className="w-3 h-3 animate-spin" /> Running...</> : <><Sparkles className="w-3 h-3" /> Run Monitor</>}
            </button>
          </div>
        </div>
        {runMessage && (
          <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 px-4 py-2 text-xs text-cyan-300">
            {runMessage}
          </div>
        )}

        <PageExplainer routeKey="market" />

        {loading ? (
          <div className="flex justify-center py-20"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>
        ) : (
          <>
            {/* Market Indicators */}
            <div className="grid grid-cols-4 gap-4">
              {(() => {
                const power = d?.market?.power;
                const carbon = d?.market?.carbon;
                const fx = d?.market?.fx;
                const unackAlerts = alerts.filter(a => !a.is_acknowledged).length;
                const critical = alerts.some(a => a.severity === 'critical' && !a.is_acknowledged);
                // metadata.average is source of truth for "live": an anchor without a numeric average is pending, not live.
                const powerHasNumber = power?.metadata?.average != null;
                const carbonHeadline = carbon?.available ? extractCarbonHeadline(carbon.content) : null;
                const fxHasNumber = fx?.metadata?.latest_rate != null;
                const indicators = [
                  {
                    label: 'Power (DE)',
                    icon: Zap,
                    color: 'text-cyan-400',
                    bg: 'bg-cyan-500/10',
                    available: powerHasNumber,
                    primary: powerHasNumber
                      ? `${power!.metadata!.average!.toFixed(2)} ${power!.metadata!.unit || 'EUR/MWh'}`
                      : null,
                    secondary: power?.metadata?.point_count != null
                      ? `${power.metadata.point_count} obs · day-ahead`
                      : power?.available
                        ? 'live anchor present, recent metadata pending'
                        : 'live data unavailable',
                  },
                  {
                    label: 'Carbon (EU ETS)',
                    icon: Flame,
                    color: 'text-amber-400',
                    bg: 'bg-amber-500/10',
                    available: !!carbonHeadline,
                    primary: carbonHeadline,
                    secondary: carbon?.metadata?.records != null
                      ? `${carbon.metadata.records} records · grid intensity`
                      : carbon?.available
                        ? 'live anchor present, recent metadata pending'
                        : 'live data unavailable',
                  },
                  {
                    label: 'EUR/USD',
                    icon: DollarSign,
                    color: 'text-purple-400',
                    bg: 'bg-purple-500/10',
                    available: fxHasNumber,
                    primary: fxHasNumber
                      ? fx!.metadata!.latest_rate!.toFixed(4)
                      : null,
                    secondary: fx?.metadata?.latest_date
                      ? `as of ${fx.metadata.latest_date}${
                          fx.metadata.period_change_pct != null
                            ? ` · ${fx.metadata.period_change_pct >= 0 ? '+' : ''}${fx.metadata.period_change_pct.toFixed(2)}%`
                            : ''
                        }`
                      : fx?.available
                        ? 'live anchor present, recent metadata pending'
                        : 'live data unavailable',
                  },
                  {
                    label: 'Alerts',
                    icon: AlertTriangle,
                    color: critical ? 'text-red-400' : unackAlerts > 0 ? 'text-amber-400' : 'text-emerald-400',
                    bg: critical ? 'bg-red-500/10' : unackAlerts > 0 ? 'bg-amber-500/10' : 'bg-emerald-500/10',
                    available: true,
                    primary: String(unackAlerts),
                    secondary: unackAlerts === 0 ? 'all clear' : unackAlerts === 1 ? 'unacknowledged' : 'unacknowledged',
                  },
                ];
                return indicators.map(ind => (
                  <div key={ind.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] text-slate-500 uppercase tracking-wider">{ind.label}</span>
                      <div className={`w-7 h-7 rounded-lg ${ind.bg} flex items-center justify-center`}><ind.icon className={`w-3.5 h-3.5 ${ind.color}`} /></div>
                    </div>
                    {ind.primary != null ? (
                      <>
                        <p className="text-xl font-bold text-white tabular-nums leading-tight">{ind.primary}</p>
                        <p className="text-[10px] text-slate-500 mt-0.5 truncate">{ind.secondary}</p>
                      </>
                    ) : (
                      <>
                        <p className="text-sm text-slate-500">—</p>
                        <p className="text-[10px] text-slate-600 mt-0.5">{ind.secondary}</p>
                      </>
                    )}
                  </div>
                ));
              })()}
            </div>

            {/* PnL KPIs */}
            {totals && (
              <div className="grid grid-cols-4 gap-4">
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <span className="text-[10px] text-slate-500 uppercase">Annual PnL</span>
                  <p className={`text-2xl font-bold mt-1 ${totals.total_annual_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {totals.total_annual_pnl >= 0 ? '+' : ''}{formatCurrency(totals.total_annual_pnl)}
                  </p>
                </motion.div>
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.05 }} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <span className="text-[10px] text-slate-500 uppercase">Mark-to-Market</span>
                  <p className={`text-2xl font-bold mt-1 ${totals.total_mtm >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {totals.total_mtm >= 0 ? '+' : ''}{formatCurrency(totals.total_mtm)}
                  </p>
                </motion.div>
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.1 }} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <span className="text-[10px] text-slate-500 uppercase">In the Money</span>
                  <p className="text-2xl font-bold mt-1 text-emerald-400 flex items-center gap-1">{totals.contracts_in_money} <ArrowUpRight className="w-4 h-4" /></p>
                </motion.div>
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
                  <span className="text-[10px] text-slate-500 uppercase">Out of Money</span>
                  <p className="text-2xl font-bold mt-1 text-red-400 flex items-center gap-1">{totals.contracts_out_of_money} <ArrowDownRight className="w-4 h-4" /></p>
                </motion.div>
              </div>
            )}

            {/* Charts Row */}
            <div className="grid grid-cols-2 gap-4">
              {/* Annual PnL by Contract */}
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white mb-4">Annual PnL by Contract</h2>
                {pnlData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={pnlData} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                      <XAxis type="number" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickFormatter={(v: number) => formatCurrency(v)} />
                      <YAxis type="category" dataKey="name" width={120} tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="pnl" name="Annual PnL" radius={[0, 4, 4, 0]}>
                        {pnlData.map((d, i) => <Cell key={i} fill={d.pnl >= 0 ? '#10b981' : '#ef4444'} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : <p className="text-xs text-slate-500 text-center py-12">No pricing data extracted yet</p>}
              </div>

              {/* Mark-to-Market Exposure */}
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white mb-4">Mark-to-Market Exposure</h2>
                {mtmData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={mtmData} layout="vertical" margin={{ left: 10, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
                      <XAxis type="number" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickFormatter={(v: number) => formatCurrency(v)} />
                      <YAxis type="category" dataKey="name" width={120} tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} />
                      <Tooltip content={<CustomTooltip />} />
                      <Bar dataKey="mtm" name="MTM" radius={[0, 4, 4, 0]}>
                        {mtmData.map((d, i) => <Cell key={i} fill={d.mtm >= 0 ? '#06b6d4' : '#f59e0b'} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : <p className="text-xs text-slate-500 text-center py-12">No exposure data</p>}
              </div>
            </div>

            {/* Contract Exposure Table */}
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
              <div className="px-5 py-4 border-b border-slate-700/50">
                <h2 className="text-sm font-semibold text-white">Portfolio Exposure Detail</h2>
              </div>
              <table className="w-full text-xs">
                <thead><tr className="border-b border-slate-700/30">
                  <th className="text-left py-2.5 px-4 text-slate-400 font-medium">Contract</th>
                  <th className="text-left py-2.5 px-4 text-slate-400 font-medium">Type</th>
                  <th className="text-right py-2.5 px-4 text-slate-400 font-medium">Contract Price</th>
                  <th className="text-right py-2.5 px-4 text-slate-400 font-medium">Spot Price</th>
                  <th className="text-right py-2.5 px-4 text-slate-400 font-medium">PnL/MWh</th>
                  <th className="text-right py-2.5 px-4 text-slate-400 font-medium">Annual PnL</th>
                  <th className="text-right py-2.5 px-4 text-slate-400 font-medium">MTM</th>
                  <th className="text-center py-2.5 px-4 text-slate-400 font-medium">Status</th>
                </tr></thead>
                <tbody>
                  {contracts.map(c => (
                    <tr key={c.id} className="border-b border-slate-700/20 hover:bg-slate-700/10">
                      <td className="py-2.5 px-4 text-white">{c.title}</td>
                      <td className="py-2.5 px-4"><span className={`px-1.5 py-0.5 rounded text-[10px] ${c.contract_type === 'ppa' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-amber-500/10 text-amber-400'}`}>{c.contract_type?.toUpperCase()}</span></td>
                      <td className="py-2.5 px-4 text-right text-slate-300 font-mono">{c.contract_price != null ? `$${c.contract_price.toFixed(2)}` : '—'}</td>
                      <td className="py-2.5 px-4 text-right text-slate-300 font-mono">${c.spot_price.toFixed(2)}</td>
                      <td className={`py-2.5 px-4 text-right font-mono ${c.pnl_per_mwh >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{c.pnl_per_mwh >= 0 ? '+' : ''}{c.pnl_per_mwh.toFixed(2)}</td>
                      <td className={`py-2.5 px-4 text-right font-mono ${c.annual_pnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{formatCurrency(c.annual_pnl)}</td>
                      <td className={`py-2.5 px-4 text-right font-mono ${c.mark_to_market >= 0 ? 'text-cyan-400' : 'text-amber-400'}`}>{formatCurrency(c.mark_to_market)}</td>
                      <td className="py-2.5 px-4 text-center">
                        {c.direction === 'in_money' ? <span className="text-emerald-400 flex items-center justify-center gap-0.5"><TrendingUp className="w-3 h-3" /> ITM</span> :
                         c.direction === 'out_of_money' ? <span className="text-red-400 flex items-center justify-center gap-0.5"><TrendingDown className="w-3 h-3" /> OTM</span> :
                         <span className="text-slate-500">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Market Alerts */}
            {alerts.length > 0 && (
              <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-5">
                <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400" /> Market Alerts
                </h2>
                <div className="space-y-2">
                  {alerts.map(a => (
                    <div key={a.id} className={`flex items-start gap-3 p-3 rounded-lg border ${
                      a.severity === 'critical' ? 'border-red-500/30 bg-red-500/5' :
                      a.severity === 'warning' ? 'border-amber-500/30 bg-amber-500/5' :
                      'border-slate-700/30 bg-slate-800/20'
                    } ${a.is_acknowledged ? 'opacity-50' : ''}`}>
                      <div className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                        a.severity === 'critical' ? 'bg-red-500' : a.severity === 'warning' ? 'bg-amber-500' : 'bg-blue-500'
                      }`} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-white font-medium">{a.title}</p>
                        <p className="text-[10px] text-slate-400 mt-0.5">{a.description}</p>
                        <p className="text-[10px] text-slate-500 mt-0.5">{a.alert_type?.replace(/_/g, ' ')} {a.delta_pct ? `(${a.delta_pct > 0 ? '+' : ''}${a.delta_pct.toFixed(1)}%)` : ''}</p>
                      </div>
                      {!a.is_acknowledged && (
                        <button onClick={() => acknowledgeAlert(a.id)}
                          className="text-xs text-slate-400 hover:text-emerald-400 transition-colors p-1" title="Acknowledge">
                          <Check className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
