'use client';

import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Beaker, Loader2, ShieldCheck, TrendingUp, History, Trash2, Calculator, Zap,
} from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, BarChart, Bar, Cell,
} from 'recharts';
import DagDrawer from '../components/DagDrawer';
import HeroBar from '../components/HeroBar';
import PipelineStrip from '../components/PipelineStrip';

const STRATEGY_PIPELINE = [
  { id: 'wingman-strategy-encoder', label: 'Encoder', kind: 'agent' as const, icon: 'sparkles' as const, hint: 'plain-English → typed rule' },
  { id: 'wingman-backtester', label: 'Backtester', kind: 'agent' as const, icon: 'cpu' as const, hint: 'historical replay on EIA + Yahoo' },
  { id: 'wingman-var-simulator', label: 'VaR (Go)', kind: 'agent' as const, icon: 'cpu' as const, hint: 'Monte Carlo Go binary — 10k sims' },
  { id: 'eia_open_data', label: 'EIA history', icon: 'db' as const },
  { id: 'code_asset', label: 'Go runner', icon: 'tool' as const, hint: 'wingman-var-simulator code asset' },
  { id: 'approval_gate', label: 'HITL gate', kind: 'sink' as const, icon: 'shield' as const, hint: 'governance approval' },
];

const SAMPLES = [
  'Lock in 10kt USGC->FE for Q1 if the spread holds above $30/MT for 5 trading days.',
  'Sell forward 25kt USGC->NWE propane any week the Mont Belvieu Argus delta is wider than 14% of WTI.',
  'Cancel all open USGC->FE positions if a Cat-3+ tropical storm is forecast within 200nm of Houston.',
];

const HISTORY_KEY = 'wingman.strategy.history.v1';

interface SavedStrategy {
  id: string;
  rule_id: string;
  intent: string;
  encoded_at: string;
  rule?: any;
  backtest?: any;
  var?: any;
  activate?: any;
}

function loadHistory(): SavedStrategy[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    return raw ? (JSON.parse(raw) as SavedStrategy[]) : [];
  } catch { return []; }
}

function saveHistory(items: SavedStrategy[]) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(HISTORY_KEY, JSON.stringify(items.slice(0, 30))); } catch { /* ignore */ }
}

export default function StrategyPage() {
  const [intent, setIntent] = useState('');
  const [loading, setLoading] = useState<'encode' | 'backtest' | 'var' | 'activate' | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [history, setHistory] = useState<SavedStrategy[]>([]);
  const [activeExecution, setActiveExecution] = useState<string | null>(null);

  useEffect(() => { setHistory(loadHistory()); }, []);

  const upsert = (s: SavedStrategy) => {
    setHistory((prev) => {
      const others = prev.filter((p) => p.id !== s.id);
      const next = [s, ...others].slice(0, 30);
      saveHistory(next);
      return next;
    });
  };

  const removeOne = (id: string) => {
    setHistory((prev) => {
      const next = prev.filter((p) => p.id !== id);
      saveHistory(next);
      return next;
    });
    if (activeId === id) setActiveId(null);
  };

  const clearAll = () => {
    if (!window.confirm('Clear all saved strategies?')) return;
    setHistory([]);
    saveHistory([]);
    setActiveId(null);
  };

  const active = useMemo(() => history.find((h) => h.id === activeId) || null, [history, activeId]);

  const encode = async () => {
    if (!intent.trim()) return;
    setLoading('encode');
    try {
      const r = await fetch('/api/wingman/strategy/encode', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent }),
      });
      const j = await r.json();
      const data = j.data || {};
      if (data.execution_id) setActiveExecution(data.execution_id);
      const id = `s-${Date.now()}`;
      const saved: SavedStrategy = {
        id,
        rule_id: data.rule_id || id,
        intent,
        encoded_at: new Date().toISOString(),
        rule: data.rule || data,
      };
      upsert(saved);
      setActiveId(id);
    } catch { /* ignore */ }
    setLoading(null);
  };

  const runBacktest = async () => {
    if (!active?.rule_id) return;
    setLoading('backtest');
    try {
      const r = await fetch(`/api/wingman/strategy/${active.rule_id}/backtest`, { method: 'POST' });
      const j = await r.json();
      if (j.data?.execution_id) setActiveExecution(j.data.execution_id);
      upsert({ ...active, backtest: j.data?.backtest || j.data });
    } catch { /* ignore */ }
    setLoading(null);
  };

  const runVar = async () => {
    if (!active?.rule_id) return;
    setLoading('var');
    try {
      const r = await fetch(`/api/wingman/strategy/${active.rule_id}/var`, { method: 'POST' });
      const j = await r.json();
      if (j.data?.execution_id) setActiveExecution(j.data.execution_id);
      upsert({ ...active, var: j.data?.var || j.data });
    } catch { /* ignore */ }
    setLoading(null);
  };

  const requestActivate = async () => {
    if (!active?.rule_id) return;
    setLoading('activate');
    try {
      const r = await fetch(`/api/wingman/strategy/${active.rule_id}/activate`, { method: 'POST' });
      const j = await r.json();
      upsert({ ...active, activate: j.data });
    } catch { /* ignore */ }
    setLoading(null);
  };

  const totals = useMemo(() => {
    const tested = history.filter((h) => h.backtest).length;
    const var_ed = history.filter((h) => h.var).length;
    const totalPnl = history.reduce((s, h) => s + (h.backtest?.total_pnl_usd ?? 0), 0);
    return { tested, var_ed, totalPnl };
  }, [history]);

  return (
    <div className="p-6">
      <HeroBar
        eyebrow="STRATEGY LAB"
        title="From plain English to live execution, gated"
        subtitle="Encode a strategy, replay it on real history, price the risk through a deployed Go Monte Carlo, and route activation through an HITL approval. Every run is saved."
        rightSlot={
          <div className="flex items-center gap-3 text-[10px]">
            <Stat2 label="saved" value={String(history.length)} />
            <Stat2 label="backtested" value={String(totals.tested)} />
            <Stat2 label="VaR'd" value={String(totals.var_ed)} />
            <Stat2 label="cum P&L" value={`${totals.totalPnl >= 0 ? '+' : '-'}$${Math.abs(totals.totalPnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}`} tone={totals.totalPnl >= 0 ? 'emerald' : 'rose'} />
          </div>
        }
      />

      <PipelineStrip
        title="Pipeline · 3 agents · Go code asset · HITL gate"
        subtitle="Encode → backtest → VaR → governance approval — every step is an SDK call you can watch"
        nodes={STRATEGY_PIPELINE}
        executionId={activeExecution}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5">
        {/* History sidebar */}
        <aside className="rounded-xl border border-slate-800 bg-slate-900/30 p-4 lg:sticky lg:top-4 self-start">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              <History className="w-3.5 h-3.5" /> History ({history.length})
            </div>
            {history.length > 0 && (
              <button onClick={clearAll} className="text-[10px] text-slate-500 hover:text-rose-300">clear</button>
            )}
          </div>
          {history.length === 0 ? (
            <div className="text-[11px] text-slate-600 italic">no saved strategies yet — encode one below</div>
          ) : (
            <div className="space-y-1.5 max-h-[60vh] overflow-y-auto -mr-2 pr-2">
              {history.map((s) => {
                const isActive = activeId === s.id;
                const pnl = s.backtest?.total_pnl_usd;
                return (
                  <div
                    key={s.id}
                    className={`group cursor-pointer rounded-lg border px-3 py-2 transition-colors ${
                      isActive
                        ? 'border-emerald-500/40 bg-emerald-500/10'
                        : 'border-slate-800 bg-slate-950/40 hover:border-slate-700'
                    }`}
                    onClick={() => setActiveId(s.id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-[11px] text-slate-200 truncate" title={s.intent}>
                          {s.intent.slice(0, 70)}
                        </div>
                        <div className="text-[9px] text-slate-600 mt-0.5 flex items-center gap-2">
                          <span>{new Date(s.encoded_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                          {pnl != null && (
                            <span className={pnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
                              ${pnl >= 0 ? '+' : ''}{pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                            </span>
                          )}
                          {s.var && <span className="text-amber-300">VaR</span>}
                          {s.activate && <span className="text-blue-300">⏳ gate</span>}
                        </div>
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); removeOne(s.id); }}
                        className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-300"
                        title="remove"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </aside>

        <div>
          {/* Compose */}
          <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-5 mb-5">
            <label className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2 block">
              Describe the strategy
            </label>
            <textarea
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              placeholder="e.g. lock in 10kt USGC->FE for Q1 if the spread holds above $30/MT for 5 trading days"
              rows={3}
              className="w-full bg-slate-950/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500 focus:outline-none"
            />
            <div className="flex flex-wrap gap-2 mt-2">
              {SAMPLES.map((s, i) => (
                <button
                  key={i}
                  onClick={() => setIntent(s)}
                  className="text-[10px] text-slate-400 hover:text-emerald-300 px-2 py-1 rounded bg-slate-800/40 hover:bg-emerald-500/10 truncate max-w-[280px]"
                  title={s}
                >
                  {s.slice(0, 60)}{s.length > 60 ? '...' : ''}
                </button>
              ))}
            </div>
            <button
              onClick={encode}
              disabled={!intent.trim() || loading === 'encode'}
              className="mt-3 px-4 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 disabled:opacity-50 text-xs font-semibold inline-flex items-center gap-2"
            >
              {loading === 'encode' ? <><Loader2 className="w-3 h-3 animate-spin" /> Encoding...</> : <><Beaker className="w-3 h-3" /> Encode + save</>}
            </button>
          </section>

          {/* Active strategy detail */}
          {active && (
            <ActiveStrategyView
              strategy={active}
              loading={loading}
              onBacktest={runBacktest}
              onVar={runVar}
              onActivate={requestActivate}
            />
          )}

          {!active && history.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/20 p-8 text-center text-sm text-slate-500">
              encode a strategy to begin — every run is saved to the history sidebar
            </div>
          )}
        </div>
      </div>

      <DagDrawer executionId={activeExecution} onClose={() => setActiveExecution(null)} />
    </div>
  );
}

function ActiveStrategyView({
  strategy, loading, onBacktest, onVar, onActivate,
}: {
  strategy: SavedStrategy;
  loading: 'encode' | 'backtest' | 'var' | 'activate' | null;
  onBacktest: () => void;
  onVar: () => void;
  onActivate: () => void;
}) {
  const bt = strategy.backtest;
  const v = strategy.var;
  const curve = bt?.equity_curve || bt?.pnl_curve || [];
  const histogram = v?.histogram || [];
  const monthly = bt?.monthly_pnl || [];

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="space-y-5">
      <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold text-emerald-300">Encoded rule</h3>
          <span className="text-[10px] font-mono text-slate-600">{strategy.rule_id}</span>
        </div>
        <pre className="text-[11px] text-slate-300 bg-slate-950/40 rounded-lg p-3 overflow-x-auto font-mono">
{JSON.stringify(strategy.rule || {}, null, 2)}
        </pre>
        <div className="flex flex-wrap gap-2 mt-3">
          <button
            onClick={onBacktest}
            disabled={loading != null}
            className="px-3 py-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20 text-xs font-semibold inline-flex items-center gap-2 disabled:opacity-50"
          >
            {loading === 'backtest' ? <Loader2 className="w-3 h-3 animate-spin" /> : <TrendingUp className="w-3 h-3" />}
            {bt ? 'Re-backtest' : 'Backtest 12 months'}
          </button>
          <button
            onClick={onVar}
            disabled={loading != null}
            className="px-3 py-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 text-xs font-semibold inline-flex items-center gap-2 disabled:opacity-50"
          >
            {loading === 'var' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Calculator className="w-3 h-3" />}
            {v ? 'Re-run VaR' : 'Run Monte Carlo VaR (Go)'}
          </button>
          {!strategy.activate && (
            <button
              onClick={onActivate}
              disabled={loading != null}
              className="px-3 py-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 text-xs font-semibold inline-flex items-center gap-2 disabled:opacity-50"
            >
              {loading === 'activate' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}
              Open governance gate to activate
            </button>
          )}
        </div>
        {strategy.activate && (
          <div className="mt-3 text-[11px] rounded-lg border border-blue-500/30 bg-blue-500/5 px-3 py-2 text-blue-200 inline-flex items-center gap-2">
            <ShieldCheck className="w-3 h-3" />
            Activation gate open · approval id <span className="font-mono">{strategy.activate.approval_id?.slice(0, 8)}</span> · head to <a href="/approvals" className="underline hover:text-blue-100">approvals</a>
          </div>
        )}
      </section>

      {bt && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-white inline-flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-cyan-300" /> Backtest — last 12 months
            </h3>
            {bt.window_label && <span className="text-[10px] text-slate-500">{bt.window_label}</span>}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 text-xs">
            <Stat label="Total P&L" v={bt.total_pnl_usd} fmt="$" tone={(bt.total_pnl_usd ?? 0) >= 0 ? 'emerald' : 'rose'} />
            <Stat label="Sharpe" v={bt.sharpe} />
            <Stat label="Max drawdown" v={bt.max_drawdown_usd} fmt="$" tone="rose" />
            <Stat label="Trades" v={bt.trades_count} />
            <Stat label="Win rate" v={bt.win_rate} fmt="%" />
            <Stat label="Avg win" v={bt.avg_win_usd} fmt="$" />
            <Stat label="Avg loss" v={bt.avg_loss_usd} fmt="$" />
            <Stat label="Profit factor" v={bt.profit_factor} />
          </div>
          {curve.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 mb-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Equity curve</div>
              <div className="h-44">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={curve}>
                    <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} width={60}
                      tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11 }}
                      formatter={(val: any) => [`$${Number(val ?? 0).toLocaleString()}`, 'cumulative']}
                    />
                    <Line type="monotone" dataKey="value" stroke="#34d399" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
          {monthly.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 mb-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Monthly P&L</div>
              <div className="h-32">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={monthly}>
                    <XAxis dataKey="month" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} width={50}
                      tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`} />
                    <Tooltip contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11 }}
                      formatter={(val: any) => [`$${Number(val ?? 0).toLocaleString()}`, 'P&L']}
                    />
                    <Bar dataKey="value">
                      {monthly.map((m: any, i: number) => (
                        <Cell key={i} fill={(m.value ?? 0) >= 0 ? '#10b981' : '#f43f5e'} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
          {bt.narrative && (
            <p className="text-xs text-slate-300 leading-relaxed border-t border-slate-800 pt-3">{bt.narrative}</p>
          )}
        </section>
      )}

      {v && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/30 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-white inline-flex items-center gap-2">
              <Calculator className="w-4 h-4 text-amber-300" /> Monte Carlo VaR
              <span className="text-[10px] font-mono text-slate-500 ml-1">{v.n_simulations?.toLocaleString?.()} sims</span>
            </h3>
            {v.horizon_days != null && <span className="text-[10px] text-slate-500">{v.horizon_days}-day horizon</span>}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4 text-xs">
            <Stat label="Mean" v={v.mean_usd} fmt="$" />
            <Stat label="P50" v={v.p50_usd} fmt="$" />
            <Stat label="P95" v={v.p95_usd} fmt="$" tone="rose" />
            <Stat label="P99" v={v.p99_usd} fmt="$" tone="rose" />
            <Stat label="ES P99" v={v.expected_shortfall_p99_usd} fmt="$" tone="rose" />
          </div>
          {histogram.length > 0 && (
            <div className="rounded-lg border border-slate-800/60 bg-slate-950/40 p-3 mb-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Outcome distribution</div>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={histogram}>
                    <XAxis dataKey="bucket" tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: '#64748b', fontSize: 9 }} axisLine={false} tickLine={false} width={36} />
                    <Tooltip contentStyle={{ background: '#0F172A', border: '1px solid #1e293b', fontSize: 11 }} />
                    <Bar dataKey="count">
                      {histogram.map((h: any, i: number) => {
                        const mid = Number(h.bucket ?? h.midpoint ?? 0);
                        const fill = mid < 0 ? '#fb7185' : mid > 0 ? '#34d399' : '#94a3b8';
                        return <Cell key={i} fill={fill} />;
                      })}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
          <div className="flex items-center gap-2 mt-2">
            <Zap className="w-3 h-3 text-amber-400" />
            <span className="text-[10px] text-slate-500 italic">
              Simulated by the deployed <span className="font-mono">wingman-var-simulator</span> Go binary (GBM walks).
              {v.data_sources && Array.isArray(v.data_sources) && (
                <> Sources: {v.data_sources.join(' · ')}</>
              )}
            </span>
          </div>
          {v.narrative && (
            <p className="text-xs text-slate-300 leading-relaxed border-t border-slate-800 pt-3 mt-3">{v.narrative}</p>
          )}
        </section>
      )}
    </motion.div>
  );
}

function Stat2({ label, value, tone }: { label: string; value: string; tone?: 'emerald' | 'rose' }) {
  const c = tone === 'emerald' ? 'text-emerald-300' : tone === 'rose' ? 'text-rose-300' : 'text-white';
  return (
    <span className="inline-flex flex-col items-end px-2.5 py-1.5 rounded-lg border border-slate-800 bg-slate-900/40">
      <span className="text-[9px] uppercase tracking-wider text-slate-500">{label}</span>
      <span className={`text-xs font-mono font-semibold ${c}`}>{value}</span>
    </span>
  );
}

function Stat({ label, v, fmt, tone }: { label: string; v: any; fmt?: string; tone?: 'emerald' | 'rose' | 'amber' }) {
  const empty = v == null || (typeof v === 'number' && Number.isNaN(v));
  const colorClass = tone === 'emerald' ? 'text-emerald-300' : tone === 'rose' ? 'text-rose-300' : tone === 'amber' ? 'text-amber-300' : 'text-white';
  if (empty) return (
    <div className="rounded-lg border border-slate-800 p-3">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className="text-base font-bold text-slate-600 mt-1">—</div>
    </div>
  );
  let display: string;
  if (typeof v === 'number') {
    if (fmt === '$') display = `${v < 0 ? '−' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    else if (fmt === '%') display = `${(v * (v < 1 ? 100 : 1)).toFixed(1)}%`;
    else display = v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  } else display = String(v);
  return (
    <div className="rounded-lg border border-slate-800 p-3">
      <div className="text-[10px] uppercase text-slate-500">{label}</div>
      <div className={`text-base font-bold mt-1 ${colorClass}`}>{display}</div>
    </div>
  );
}
