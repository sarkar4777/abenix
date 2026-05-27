'use client';

import { useState } from 'react';
import { BellRing, ArrowUpRight, TrendingUp, TrendingDown, ShieldCheck, FileText, Sparkles } from 'lucide-react';

interface Recommendation {
  id: string;
  desk: 'gas' | 'power' | 'lng' | 'environmental' | 'cross';
  action: 'buy' | 'sell' | 'hedge' | 'hold';
  subject: string;
  thesis: string;
  pvEur: number;
  confidence: number;
  drivers: string[];
  status: 'open' | 'awaiting-approval' | 'approved' | 'rejected';
}

const RECS: Recommendation[] = [
  {
    id: 'r-001', desk: 'gas', action: 'buy', subject: 'TTF M+1 vs Q1+1 spread',
    thesis: 'Front-month / Q1 spread is €7.4 above 5y avg with cold-snap forecast PSI shifting demand right. Storage cycling rec: buy front, sell Q1.',
    pvEur: 240_000, confidence: 0.87,
    drivers: ['HDD +14% vs norm', 'Storage 92% full', 'EUA at €87/t', 'Spread > 2σ from 5y avg'],
    status: 'awaiting-approval',
  },
  {
    id: 'r-002', desk: 'power', action: 'hedge', subject: 'DE-Power Cal+1',
    thesis: 'BayesianRidge fair-value €91.3 vs blended €95.6 → 1.8σ short signal. Wind 7-day forecast 18% above norm reinforces.',
    pvEur: 180_000, confidence: 0.82,
    drivers: ['Wind +18% forecast', 'Clean-spark +€18', 'PMI 52.4 plateaued'],
    status: 'open',
  },
  {
    id: 'r-003', desk: 'lng', action: 'sell', subject: 'Krk Q1 send-out vs TTF',
    thesis: 'Cargo book locked through Q1 at $11.80/MMBtu vs TTF Q1 implying €38 — €6/MWh structural carry. Optimal: pre-sell 2 cargoes Q2.',
    pvEur: 310_000, confidence: 0.91,
    drivers: ['Slot calendar full Q1', 'TTF Q1 €38.20', 'Henry-TTF basis +$2.10'],
    status: 'open',
  },
  {
    id: 'r-004', desk: 'environmental', action: 'buy', subject: 'EUA Dec-25',
    thesis: 'Bayesian prior shifts probability of €100/t in next 90 days to 38% from 22% last week — EU ETS supply tightening + auction calendar gap.',
    pvEur: 95_000, confidence: 0.74,
    drivers: ['Supply tight Q4', 'Auction gap Nov 12-26', 'Linkage premium widening'],
    status: 'approved',
  },
  {
    id: 'r-005', desk: 'cross', action: 'hold', subject: 'Industrial baseload book',
    thesis: 'Forecast residuals < 1σ; no anomaly flag; recommend no rebalance this week.',
    pvEur: 0, confidence: 0.93,
    drivers: ['MAPE 1.51% — best in class', 'PSI 0.18 — stable'],
    status: 'open',
  },
];

const ACTION_STYLES: Record<Recommendation['action'], { tone: string; Icon: any; label: string }> = {
  buy:    { tone: 'emerald', Icon: TrendingUp, label: 'BUY' },
  sell:   { tone: 'rose',    Icon: TrendingDown, label: 'SELL' },
  hedge:  { tone: 'cyan',    Icon: ShieldCheck, label: 'HEDGE' },
  hold:   { tone: 'slate',   Icon: FileText, label: 'HOLD' },
};

const STATUS_STYLES: Record<Recommendation['status'], string> = {
  open: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/30',
  'awaiting-approval': 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  approved: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
  rejected: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
};

export default function RecommendationsPage() {
  const [filter, setFilter] = useState<'all' | Recommendation['desk']>('all');
  const view = filter === 'all' ? RECS : RECS.filter(r => r.desk === filter);
  const totalPV = view.reduce((a, r) => a + (r.action === 'hold' ? 0 : r.pvEur), 0);

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <BellRing className="w-7 h-7 text-amber-400" />
          <h1 className="text-3xl font-bold text-white">Recommendations</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          LLM-synthesised theses from the forecasts + price engine + anomaly signals. Every actionable rec routes through
          Approvals before execution.
        </p>
      </header>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-[11px] text-slate-500 uppercase tracking-wider">Open recs</p>
          <p className="text-2xl font-bold text-white mt-1.5">{view.filter(r => r.status === 'open').length}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-[11px] text-slate-500 uppercase tracking-wider">Awaiting approval</p>
          <p className="text-2xl font-bold text-amber-300 mt-1.5">{view.filter(r => r.status === 'awaiting-approval').length}</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-[11px] text-slate-500 uppercase tracking-wider">Total PV (open)</p>
          <p className="text-2xl font-bold text-emerald-300 mt-1.5">€{(totalPV / 1000).toFixed(0)}k</p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <p className="text-[11px] text-slate-500 uppercase tracking-wider">Avg confidence</p>
          <p className="text-2xl font-bold text-cyan-300 mt-1.5">{(view.reduce((a, r) => a + r.confidence, 0) / view.length * 100).toFixed(0)}%</p>
        </div>
      </div>

      <div className="flex gap-2 mb-4">
        {(['all', 'gas', 'power', 'lng', 'environmental', 'cross'] as const).map(d => (
          <button
            key={d}
            onClick={() => setFilter(d)}
            className={`px-3 py-1.5 rounded-md text-xs border transition-colors capitalize ${
              filter === d
                ? 'bg-amber-500/15 text-amber-200 border-amber-500/40'
                : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:bg-slate-800/60 hover:text-white'
            }`}
          >
            {d}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {view.map(r => {
          const A = ACTION_STYLES[r.action];
          return (
            <div key={r.id} className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 hover:border-slate-700 transition-colors">
              <div className="flex items-start gap-4">
                <div className={`shrink-0 px-3 py-2 rounded-lg border bg-${A.tone}-500/15 border-${A.tone}-500/40 text-${A.tone}-200 flex flex-col items-center min-w-[80px]`}>
                  <A.Icon className="w-5 h-5 mb-1" />
                  <p className="text-[10px] font-bold tracking-wider">{A.label}</p>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-3 mb-1.5">
                    <p className="text-white font-semibold">{r.subject}</p>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded border ${STATUS_STYLES[r.status]}`}>{r.status}</span>
                      <span className="text-[10px] uppercase tracking-wider text-slate-500 bg-slate-900 border border-slate-800 px-2 py-0.5 rounded">{r.desk}</span>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed mb-3 flex items-start gap-1.5">
                    <Sparkles className="w-3 h-3 text-amber-400 mt-0.5 shrink-0" />
                    <span>{r.thesis}</span>
                  </p>
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    {r.drivers.map(d => (
                      <span key={d} className="text-[10px] bg-slate-800/60 text-slate-400 border border-slate-700/60 rounded px-1.5 py-0.5">{d}</span>
                    ))}
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4 text-xs">
                      <span className="text-slate-500">PV</span>
                      <span className={`font-mono font-semibold ${r.pvEur > 0 ? 'text-emerald-300' : 'text-slate-400'}`}>
                        {r.pvEur > 0 ? `+€${(r.pvEur / 1000).toFixed(0)}k` : '—'}
                      </span>
                      <span className="text-slate-500 ml-3">Conf</span>
                      <span className="font-mono text-cyan-300">{(r.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <a href="/workbench" className="text-xs text-slate-400 hover:text-white flex items-center gap-1">
                      Open workbench <ArrowUpRight className="w-3 h-3" />
                    </a>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
