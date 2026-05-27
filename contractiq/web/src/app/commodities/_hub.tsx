'use client';

import { useState } from 'react';
import {
  TrendingUp, LineChart, AlertOctagon, FileText, ArrowUpRight, Sparkles,
} from 'lucide-react';

export interface HubConfig {
  slug: 'gas' | 'power' | 'lng' | 'environmental';
  title: string;
  subtitle: string;
  accent: 'orange' | 'amber' | 'sky' | 'emerald';
  icon: any;
  hubs: { name: string; spot: number; unit: string; change: number }[];
  curve: { tenor: string; mid: number }[];
  signals: { id: string; severity: 'info' | 'warn' | 'high'; text: string }[];
  contracts: { id: string; cp: string; vol: string; status: string }[];
  glossary: { term: string; def: string }[];
}

const ACCENTS: Record<HubConfig['accent'], { ring: string; chip: string; text: string; bg: string }> = {
  orange:  { ring: 'from-orange-500 via-amber-500 to-red-500', chip: 'bg-orange-500/15 text-orange-200 border-orange-500/40', text: 'text-orange-300', bg: 'bg-orange-500/5' },
  amber:   { ring: 'from-amber-400 via-yellow-500 to-orange-500', chip: 'bg-amber-500/15 text-amber-200 border-amber-500/40', text: 'text-amber-300', bg: 'bg-amber-500/5' },
  sky:     { ring: 'from-sky-500 via-cyan-500 to-blue-500', chip: 'bg-sky-500/15 text-sky-200 border-sky-500/40', text: 'text-sky-300', bg: 'bg-sky-500/5' },
  emerald: { ring: 'from-emerald-500 via-green-500 to-teal-500', chip: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/40', text: 'text-emerald-300', bg: 'bg-emerald-500/5' },
};

const SIGNAL_STYLES = {
  info: 'bg-slate-800/60 text-slate-300 border-slate-700',
  warn: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  high: 'bg-rose-500/10 text-rose-300 border-rose-500/30',
};

export function CommodityHub({ cfg }: { cfg: HubConfig }) {
  const A = ACCENTS[cfg.accent];
  const Ic = cfg.icon;
  const w = 920, h = 220;
  const yMin = Math.min(...cfg.curve.map(p => p.mid)) * 0.95;
  const yMax = Math.max(...cfg.curve.map(p => p.mid)) * 1.05;
  const xs = (i: number) => 50 + (i / (cfg.curve.length - 1)) * (w - 70);
  const ys = (v: number) => h - 30 - ((v - yMin) / (yMax - yMin)) * (h - 60);
  const path = cfg.curve.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xs(i)} ${ys(p.mid)}`).join(' ');

  return (
    <div className="min-h-screen text-slate-200 p-8 max-w-[1400px] mx-auto">
      <header className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${A.ring} flex items-center justify-center shadow-lg`}>
            <Ic className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-white">{cfg.title}</h1>
            <p className="text-slate-400 text-sm mt-0.5">{cfg.subtitle}</p>
          </div>
        </div>
        <p className="text-xs text-slate-500 mt-3 max-w-3xl">
          This page is a <strong className="text-slate-400">filtered view</strong> into Data Fabric, Forecaster, Price Engine
          and Recommendations — every number you see here lives in those cross-commodity engines, just sliced to
          {' '}{cfg.title.toLowerCase()}.
        </p>
      </header>

      <section className="grid grid-cols-4 gap-3 mb-6">
        {cfg.hubs.map(h => (
          <div key={h.name} className={`rounded-xl border border-slate-800 p-4 ${A.bg}`}>
            <p className="text-[11px] text-slate-500 uppercase tracking-wider">{h.name}</p>
            <p className="text-xl font-bold text-white mt-1 font-mono">{h.spot.toFixed(2)} <span className="text-[11px] text-slate-500 font-sans">{h.unit}</span></p>
            <p className={`text-[11px] mt-0.5 font-mono ${h.change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
              {h.change >= 0 ? '+' : ''}{h.change.toFixed(2)}%
            </p>
          </div>
        ))}
      </section>

      <div className="grid grid-cols-12 gap-6 mb-6">
        <section className="col-span-8 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2"><LineChart className={`w-4 h-4 ${A.text}`} /> Forward curve</h2>
            <a href="/price-engine" className="text-xs text-slate-400 hover:text-white flex items-center gap-1">
              Open price engine <ArrowUpRight className="w-3 h-3" />
            </a>
          </div>
          <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto">
            {[0, 0.25, 0.5, 0.75, 1].map(g => {
              const y = 30 + g * (h - 60);
              return <line key={g} x1="50" x2={w - 20} y1={y} y2={y} stroke="#1e293b" strokeDasharray="2 4" strokeWidth="0.5" />;
            })}
            <path d={path} stroke="#10b981" strokeWidth="2.5" fill="none" />
            {cfg.curve.map((p, i) => (
              <circle key={p.tenor} cx={xs(i)} cy={ys(p.mid)} r="3" fill="#0B0F19" stroke="#10b981" strokeWidth="2" />
            ))}
            {cfg.curve.map((p, i) => (
              <text key={p.tenor + 'l'} x={xs(i)} y={h - 8} textAnchor="middle" fill="#64748b" fontSize="10">{p.tenor}</text>
            ))}
            <text x="46" y="30" textAnchor="end" fill="#64748b" fontSize="10">{yMax.toFixed(1)}</text>
            <text x="46" y={h - 30} textAnchor="end" fill="#64748b" fontSize="10">{yMin.toFixed(1)}</text>
          </svg>
        </section>

        <section className="col-span-4 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-1.5"><AlertOctagon className="w-3.5 h-3.5 text-amber-400" /> Live signals</h2>
            <a href="/recommendations" className="text-[11px] text-slate-500 hover:text-white">All →</a>
          </div>
          <ul className="space-y-2">
            {cfg.signals.map(s => (
              <li key={s.id} className={`text-xs p-2.5 rounded-md border ${SIGNAL_STYLES[s.severity]}`}>
                <p>{s.text}</p>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="grid grid-cols-12 gap-6">
        <section className="col-span-7 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="text-sm font-semibold text-white flex items-center gap-1.5"><FileText className={`w-3.5 h-3.5 ${A.text}`} /> Active contracts</h2>
            <a href="/contracts" className="text-[11px] text-slate-500 hover:text-white">All contracts →</a>
          </div>
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="text-left py-2">Contract</th>
                <th className="text-left py-2">Counterparty</th>
                <th className="text-left py-2">Volume</th>
                <th className="text-left py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {cfg.contracts.map(c => (
                <tr key={c.id} className="border-b border-slate-800/40 hover:bg-slate-800/20">
                  <td className="py-2.5 text-slate-200 font-mono">{c.id}</td>
                  <td className="py-2.5 text-slate-300">{c.cp}</td>
                  <td className="py-2.5 text-slate-400">{c.vol}</td>
                  <td className="py-2.5">
                    <span className={`text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${A.chip}`}>{c.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="col-span-5 rounded-xl border border-slate-800 bg-slate-900/40 p-6">
          <h2 className="text-sm font-semibold text-white flex items-center gap-1.5 mb-3"><Sparkles className={`w-3.5 h-3.5 ${A.text}`} /> Glossary</h2>
          <dl className="space-y-3">
            {cfg.glossary.map(g => (
              <div key={g.term}>
                <dt className="text-xs font-semibold text-white">{g.term}</dt>
                <dd className="text-[11px] text-slate-500 leading-relaxed mt-0.5">{g.def}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      <section className="mt-6 grid grid-cols-3 gap-3">
        <a href="/forecaster" className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 hover:bg-slate-800/40 transition-colors">
          <div className="flex items-center justify-between mb-1">
            <p className="text-sm font-semibold text-white flex items-center gap-1.5"><TrendingUp className="w-4 h-4 text-emerald-400" /> Open forecast</p>
            <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
          </div>
          <p className="text-[11px] text-slate-500">Live offtake fan chart with SHAP drivers, scoped to {cfg.title.toLowerCase()}.</p>
        </a>
        <a href="/price-engine" className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 hover:bg-slate-800/40 transition-colors">
          <div className="flex items-center justify-between mb-1">
            <p className="text-sm font-semibold text-white flex items-center gap-1.5"><LineChart className="w-4 h-4 text-violet-400" /> Open price engine</p>
            <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
          </div>
          <p className="text-[11px] text-slate-500">Three-layer hybrid curve with stress tests for {cfg.title.toLowerCase()} hubs.</p>
        </a>
        <a href="/workbench" className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 hover:bg-slate-800/40 transition-colors">
          <div className="flex items-center justify-between mb-1">
            <p className="text-sm font-semibold text-white flex items-center gap-1.5"><Sparkles className="w-4 h-4 text-cyan-400" /> Open workbench</p>
            <ArrowUpRight className="w-3.5 h-3.5 text-slate-500" />
          </div>
          <p className="text-[11px] text-slate-500">SHAP waterfall + analyst override + annotations, filtered.</p>
        </a>
      </section>
    </div>
  );
}
