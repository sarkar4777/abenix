'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Gauge, Play, Loader2, TrendingUp, TrendingDown, Cloud, Wind,
  Sun, Thermometer, Droplets, Newspaper, AlertTriangle, CheckCircle2,
  BarChart3, GitBranch, Zap, DollarSign, Activity, Target, ChevronDown,
  ChevronRight, RefreshCw,
} from 'lucide-react';

import { apiFetch } from '@/lib/api';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('contractiq_token');
}

// ─── Types ─────────────────────────────────────────────────────────────

interface Contract {
  id: string;
  title: string;
  contract_type: string;
  status: string;
  total_capacity_mw: number | null;
}

interface SimResult {
  simulation_type: string;
  scope: string;
  results: any;
  model: string;
  duration_ms: number;
  cost: number;
  tool_calls: number;
}

type SimType = 'weather_impact' | 'price_sensitivity' | 'monte_carlo' | 'sentiment_impact' | 'full_stress_test';

const SIM_TYPES: { id: SimType; label: string; icon: any; description: string; color: string }[] = [
  { id: 'weather_impact', label: 'Weather Impact', icon: Cloud, description: 'Solar irradiance, wind speed, temperature scenarios on energy yield', color: 'cyan' },
  { id: 'price_sensitivity', label: 'Price Sensitivity', icon: TrendingUp, description: 'Sweep contract pricing ±20% — see NPV, IRR, LCOE impact', color: 'amber' },
  { id: 'monte_carlo', label: 'Monte Carlo', icon: Activity, description: '1000-iteration probabilistic simulation of portfolio NPV', color: 'purple' },
  { id: 'sentiment_impact', label: 'Sentiment Analysis', icon: Newspaper, description: 'Assess market news impact on risk premiums and valuations', color: 'rose' },
  { id: 'full_stress_test', label: 'Full Stress Test', icon: Gauge, description: 'Combined weather + price + sentiment + Monte Carlo — the works', color: 'emerald' },
];

// Literal class lookup tables — Tailwind JIT can only keep classes it can see verbatim.
const SIM_SELECTED_CLASSES: Record<string, string> = {
  cyan:    'border-cyan-500/50 bg-cyan-500/10 ring-2 ring-cyan-500/20',
  amber:   'border-amber-500/50 bg-amber-500/10 ring-2 ring-amber-500/20',
  purple:  'border-purple-500/50 bg-purple-500/10 ring-2 ring-purple-500/20',
  rose:    'border-rose-500/50 bg-rose-500/10 ring-2 ring-rose-500/20',
  emerald: 'border-emerald-500/50 bg-emerald-500/10 ring-2 ring-emerald-500/20',
};

const SIM_ICON_BG_CLASSES: Record<string, string> = {
  cyan:    'bg-cyan-500/10',
  amber:   'bg-amber-500/10',
  purple:  'bg-purple-500/10',
  rose:    'bg-rose-500/10',
  emerald: 'bg-emerald-500/10',
};

const SIM_ICON_TEXT_CLASSES: Record<string, string> = {
  cyan:    'text-cyan-400',
  amber:   'text-amber-400',
  purple:  'text-purple-400',
  rose:    'text-rose-400',
  emerald: 'text-emerald-400',
};

// ─── Simulation Control Panel ──────────────────────────────────────────

function SimTypeCard({ sim, selected, onClick }: { sim: typeof SIM_TYPES[0]; selected: boolean; onClick: () => void }) {
  const Icon = sim.icon;
  return (
    <button
      onClick={onClick}
      data-testid={`sim-type-${sim.id}`}
      className={`text-left p-4 rounded-xl border transition-all ${
        selected
          ? (SIM_SELECTED_CLASSES[sim.color] ?? SIM_SELECTED_CLASSES.cyan)
          : 'border-slate-700/50 bg-slate-800/30 hover:border-slate-600/50'
      }`}
    >
      <div className="flex items-center gap-3 mb-2">
        <div className={`w-9 h-9 rounded-lg ${SIM_ICON_BG_CLASSES[sim.color] ?? SIM_ICON_BG_CLASSES.cyan} flex items-center justify-center`}>
          <Icon className={`w-5 h-5 ${SIM_ICON_TEXT_CLASSES[sim.color] ?? SIM_ICON_TEXT_CLASSES.cyan}`} />
        </div>
        <div>
          <p className="text-sm font-semibold text-white">{sim.label}</p>
        </div>
      </div>
      <p className="text-[10px] text-slate-400 leading-relaxed">{sim.description}</p>
    </button>
  );
}

// ─── Parameter Controls ────────────────────────────────────────────────

function ParameterPanel({ simType, params, onChange }: {
  simType: SimType;
  params: Record<string, any>;
  onChange: (p: Record<string, any>) => void;
}) {
  const set = (k: string, v: any) => onChange({ ...params, [k]: v });

  return (
    <div className="space-y-3" data-testid="sim-params">
      {(simType === 'weather_impact' || simType === 'full_stress_test') && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 space-y-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <Cloud className="w-3 h-3" /> Weather Parameters
          </p>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[10px] text-slate-400">
              Location
              <input value={params.location || 'Northern Europe'} onChange={e => set('location', e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white" />
            </label>
            <label className="text-[10px] text-slate-400">
              Period (months)
              <input type="number" value={params.period_months || 12} onChange={e => set('period_months', +e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white" />
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            {['solar_irradiance', 'wind_speed', 'temperature', 'precipitation'].map(p => (
              <label key={p} className="inline-flex items-center gap-1.5 text-[10px] text-slate-400">
                <input type="checkbox" checked={(params.weather_params || ['solar_irradiance', 'wind_speed', 'temperature']).includes(p)}
                  onChange={e => {
                    const cur = params.weather_params || ['solar_irradiance', 'wind_speed', 'temperature'];
                    set('weather_params', e.target.checked ? [...cur, p] : cur.filter((x: string) => x !== p));
                  }}
                  className="rounded border-slate-600"
                />
                {p.replace('_', ' ')}
              </label>
            ))}
          </div>
        </div>
      )}

      {(simType === 'price_sensitivity' || simType === 'full_stress_test') && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 space-y-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <DollarSign className="w-3 h-3" /> Price Parameters
          </p>
          <div className="grid grid-cols-3 gap-2">
            <label className="text-[10px] text-slate-400">
              Price variation (%)
              <input type="number" value={params.price_variation_pct || 20} onChange={e => set('price_variation_pct', +e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white" />
            </label>
            <label className="text-[10px] text-slate-400">
              Steps
              <input type="number" value={params.price_steps || 5} onChange={e => set('price_steps', +e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white" />
            </label>
            <label className="text-[10px] text-slate-400">
              Discount rate (%)
              <input type="number" step="0.5" value={params.discount_rate || 7} onChange={e => set('discount_rate', +e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white" />
            </label>
          </div>
        </div>
      )}

      {(simType === 'monte_carlo' || simType === 'full_stress_test') && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 space-y-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <Activity className="w-3 h-3" /> Monte Carlo Parameters
          </p>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-[10px] text-slate-400">
              Iterations
              <select value={params.iterations || 1000} onChange={e => set('iterations', +e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white">
                <option value={100}>100 (fast)</option>
                <option value={1000}>1,000 (standard)</option>
                <option value={5000}>5,000 (detailed)</option>
                <option value={10000}>10,000 (high precision)</option>
              </select>
            </label>
            <label className="text-[10px] text-slate-400">
              Confidence level (%)
              <select value={params.confidence_level || 95} onChange={e => set('confidence_level', +e.target.value)}
                className="mt-0.5 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white">
                <option value={90}>90%</option>
                <option value={95}>95%</option>
                <option value={99}>99%</option>
              </select>
            </label>
          </div>
        </div>
      )}

      {(simType === 'sentiment_impact' || simType === 'full_stress_test') && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 space-y-2">
          <p className="text-[10px] text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
            <Newspaper className="w-3 h-3" /> Sentiment / News Headlines
          </p>
          <textarea
            value={params.news_headlines_text || ''}
            onChange={e => set('news_headlines_text', e.target.value)}
            placeholder="Paste news headlines (one per line):\n\nEU power prices surge on gas supply fears\nRecord solar installations expected in 2026\nCarbon ETS prices hit €90/ton..."
            className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-2 text-xs text-white min-h-[80px] placeholder-slate-600"
          />
        </div>
      )}
    </div>
  );
}

// ─── Results Visualization ─────────────────────────────────────────────

// Client-side rescue parser — tries hard to recover JSON from agent
// output even when the backend stored it as raw text. Mirrors the
// backend's robust strategy.
function recoverJson(text: string): any | null {
  if (!text || typeof text !== 'string') return null;
  let s = text.trim();
  const m = s.match(/```(?:json)?\s*\n?([\s\S]*?)```/);
  if (m) s = m[1].trim();
  try { return JSON.parse(s); } catch { /* try brace span */ }
  const a = s.indexOf('{'), b = s.lastIndexOf('}');
  if (a !== -1 && b > a) {
    try { return JSON.parse(s.slice(a, b + 1)); } catch { /* fall through */ }
  }
  return null;
}

// Map a top-level key to a friendly section spec.
function sectionMeta(key: string): { label: string; icon: any } {
  const k = key.toLowerCase();
  if (/(weather|wind|solar|irradiance|temperature)/.test(k)) return { label: titleize(key), icon: Cloud };
  if (/(price|pricing|npv|irr|lcoe|valuation|cashflow|sensitivity)/.test(k)) return { label: titleize(key), icon: DollarSign };
  if (/(monte|distribution|p\d+|percentile|stoch)/.test(k)) return { label: titleize(key), icon: Activity };
  if (/(sentiment|news|headline|market)/.test(k)) return { label: titleize(key), icon: Newspaper };
  if (/(dag|graph|dependenc)/.test(k)) return { label: titleize(key), icon: GitBranch };
  if (/(summary|recommend|conclusion|executive|insight)/.test(k)) return { label: titleize(key), icon: Target };
  if (/(risk|stress|scenario)/.test(k)) return { label: titleize(key), icon: AlertTriangle };
  if (/(contract|asset|counterparty|portfolio|detail)/.test(k)) return { label: titleize(key), icon: Target };
  return { label: titleize(key), icon: Target };
}

function titleize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function isPrimitive(v: any): boolean {
  return v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean';
}

function formatPrimitive(v: any): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
    return String(Math.round(v * 10000) / 10000);
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  return String(v);
}

// Render any value: primitives → text, arrays → table, objects → grid.
function ValueView({ value }: { value: any }) {
  if (isPrimitive(value)) {
    return <span className="text-slate-200 font-mono text-[12px]">{formatPrimitive(value)}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-slate-600 italic text-[11px]">(empty)</span>;
    // Array of primitives — comma-list (cap)
    if (value.every(isPrimitive)) {
      const head = value.slice(0, 12).map(formatPrimitive).join(', ');
      return <span className="text-slate-200 text-[12px]">{head}{value.length > 12 ? `  …(+${value.length - 12})` : ''}</span>;
    }
    // Array of objects → table with union of keys
    if (value.every(v => v && typeof v === 'object' && !Array.isArray(v))) {
      const cols = Array.from(new Set(value.flatMap(o => Object.keys(o)))).slice(0, 8);
      return (
        <div className="overflow-x-auto">
          <table className="text-[11px] w-full">
            <thead className="text-slate-500">
              <tr>{cols.map(c => <th key={c} className="text-left font-medium px-2 py-1 whitespace-nowrap">{titleize(c)}</th>)}</tr>
            </thead>
            <tbody>
              {value.slice(0, 25).map((row, i) => (
                <tr key={i} className="border-t border-slate-800/60">
                  {cols.map(c => (
                    <td key={c} className="px-2 py-1 align-top">
                      {isPrimitive(row[c])
                        ? <span className="text-slate-200">{formatPrimitive(row[c])}</span>
                        : <span className="text-slate-500 italic">{Array.isArray(row[c]) ? `[${row[c].length}]` : '{…}'}</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {value.length > 25 && <p className="text-[10px] text-slate-500 mt-1">+{value.length - 25} more rows</p>}
        </div>
      );
    }
    // Mixed array → JSON
    return (
      <pre className="text-[10px] text-slate-300 bg-slate-900/50 rounded-lg p-3 max-h-60 overflow-auto">{JSON.stringify(value, null, 2)}</pre>
    );
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value);
    return (
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-baseline gap-2 text-[12px] min-w-0">
            <span className="text-slate-500 text-[10px] uppercase tracking-wider shrink-0 truncate" title={k}>{titleize(k)}</span>
            <span className="flex-1 min-w-0 text-right">
              {isPrimitive(v)
                ? <span className="text-slate-200 font-mono">{formatPrimitive(v)}</span>
                : <span className="text-slate-500 italic">{Array.isArray(v) ? `[${v.length} items]` : '{…}'}</span>}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

function ResultsPanel({ result }: { result: SimResult }) {
  const r0 = result.results || {};

  // If backend gave us only raw_output, try to parse client-side as a rescue.
  const r: any = useMemo(() => {
    if (r0.raw_output && Object.keys(r0).length <= 2) {
      const recovered = recoverJson(r0.raw_output);
      if (recovered && typeof recovered === 'object') return recovered;
    }
    return r0;
  }, [r0]);

  const parseFailed = r0.parse_error && r === r0;

  // Pick out a summary line (most agents emit one)
  const summary: string | null = useMemo(() => {
    for (const k of ['summary', 'executive_summary', 'recommendation', 'conclusion']) {
      const v = r[k];
      if (typeof v === 'string' && v.trim()) return v;
    }
    return null;
  }, [r]);

  // Top-level scalars become a compact "Overview" grid
  const overviewEntries = useMemo(
    () => Object.entries(r).filter(([k, v]) => isPrimitive(v) && k !== 'summary' && k !== 'executive_summary' && k !== 'recommendation' && k !== 'conclusion'),
    [r],
  );

  // Every other top-level key becomes its own collapsible section
  const sections = useMemo(() => {
    const out: { id: string; label: string; icon: any; content: any }[] = [];
    for (const [k, v] of Object.entries(r)) {
      if (isPrimitive(v)) continue;
      if (k === 'raw_output') continue;
      const meta = sectionMeta(k);
      out.push({ id: k, label: meta.label, icon: meta.icon, content: v });
    }
    return out;
  }, [r]);

  // Default-expand the first 2 sections + always summary
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(sections.slice(0, 2).map(s => s.id)));
  const toggle = (k: string) => setExpanded(prev => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <div className="space-y-3" data-testid="sim-results">
      {/* KPI strip */}
      <div className="grid grid-cols-4 gap-2">
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 text-center">
          <p className="text-lg font-bold text-cyan-400">{result.tool_calls}</p>
          <p className="text-[9px] text-slate-500">Tool Calls</p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 text-center">
          <p className="text-lg font-bold text-purple-400">{((result.duration_ms || 0) / 1000).toFixed(1)}s</p>
          <p className="text-[9px] text-slate-500">Duration</p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 text-center">
          <p className="text-lg font-bold text-emerald-400">${(result.cost || 0).toFixed(4)}</p>
          <p className="text-[9px] text-slate-500">Cost</p>
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg p-3 text-center">
          <p className="text-lg font-bold text-amber-400">{sections.length}</p>
          <p className="text-[9px] text-slate-500">Sections</p>
        </div>
      </div>

      {parseFailed && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-[12px] text-amber-100 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-300 mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold text-amber-200">Agent output was not valid JSON</p>
            <p className="mt-0.5 text-amber-100/80">Showing the raw response below — re-run the simulation, or open Executions in Abenix to inspect.</p>
          </div>
        </div>
      )}

      {/* Executive summary at the top */}
      {summary && (
        <div className="bg-emerald-500/5 border border-emerald-500/30 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1.5">
            <Target className="w-4 h-4 text-emerald-400" />
            <span className="text-[11px] uppercase tracking-wider text-emerald-300 font-semibold">Executive Summary</span>
          </div>
          <p className="text-[13px] text-slate-100 leading-relaxed whitespace-pre-wrap">{summary}</p>
        </div>
      )}

      {/* Overview grid — top-level scalars */}
      {overviewEntries.length > 0 && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <Target className="w-4 h-4 text-cyan-400" />
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Overview</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2">
            {overviewEntries.map(([k, v]) => (
              <div key={k} className="text-[12px] flex justify-between gap-2 min-w-0">
                <span className="text-slate-500 truncate" title={k}>{titleize(k)}</span>
                <span className="text-slate-100 font-mono truncate text-right" title={String(v)}>{formatPrimitive(v)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Auto-discovered sections */}
      {sections.map(s => {
        const Icon = s.icon;
        const isOpen = expanded.has(s.id);
        return (
          <div key={s.id} className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
            <button onClick={() => toggle(s.id)}
              className="w-full flex items-center gap-3 p-3.5 hover:bg-slate-700/20 transition-colors text-left">
              <Icon className="w-4 h-4 text-cyan-400 shrink-0" />
              <span className="text-sm font-medium text-white flex-1">{s.label}</span>
              <span className="text-[10px] text-slate-500">
                {Array.isArray(s.content) ? `${s.content.length} item${s.content.length !== 1 ? 's' : ''}` : `${Object.keys(s.content || {}).length} fields`}
              </span>
              {isOpen ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
            </button>
            <AnimatePresence>
              {isOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
                  <div className="px-4 pb-4 border-t border-slate-700/50 pt-3">
                    {s.id === 'dag' && s.content?.nodes ? (
                      <SimDAG data={s.content} />
                    ) : (
                      <ValueView value={s.content} />
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}

      {/* Last-resort raw output (only if nothing parseable was rendered) */}
      {sections.length === 0 && overviewEntries.length === 0 && r0.raw_output && (
        <div className="bg-slate-900/50 border border-slate-700/50 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4 text-slate-400" />
            <span className="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Raw agent output</span>
          </div>
          <pre className="text-[11px] text-slate-300 whitespace-pre-wrap break-words max-h-96 overflow-y-auto leading-relaxed">{r0.raw_output}</pre>
        </div>
      )}
    </div>
  );
}

// ─── Simulation DAG Visualization ──────────────────────────────────────

function SimDAG({ data }: { data: any }) {
  const nodes: Array<{ id: string; label: string; type: string }> = data.nodes || [];
  const edges: Array<{ from: string; to: string }> = data.edges || [];

  const nw = 160, nh = 40, gx = 40, gy = 16;
  const levels: Record<string, number> = {};
  // Simple level assignment
  const visited = new Set<string>();
  const adj: Record<string, string[]> = {};
  edges.forEach(e => { (adj[e.from] = adj[e.from] || []).push(e.to); });
  const roots = nodes.filter(n => !edges.some(e => e.to === n.id));
  const queue = roots.map(n => n.id);
  queue.forEach(id => { levels[id] = 0; });
  while (queue.length) {
    const id = queue.shift()!;
    if (visited.has(id)) continue;
    visited.add(id);
    (adj[id] || []).forEach(child => {
      levels[child] = Math.max(levels[child] || 0, (levels[id] || 0) + 1);
      queue.push(child);
    });
  }
  nodes.forEach(n => { if (!(n.id in levels)) levels[n.id] = 0; });

  // Position by level
  const byLevel: Record<number, string[]> = {};
  Object.entries(levels).forEach(([id, lv]) => { (byLevel[lv] = byLevel[lv] || []).push(id); });
  const positions: Record<string, { x: number; y: number }> = {};
  Object.entries(byLevel).forEach(([lv, ids]) => {
    ids.forEach((id, row) => {
      positions[id] = { x: 20 + +lv * (nw + gx), y: 20 + row * (nh + gy) };
    });
  });

  const maxLv = Math.max(0, ...Object.values(levels));
  const maxRow = Math.max(1, ...Object.values(byLevel).map(a => a.length));
  const svgW = (maxLv + 1) * (nw + gx) + 40;
  const svgH = maxRow * (nh + gy) + 40;

  const colors: Record<string, string> = {
    weather: '#06b6d4', price: '#f59e0b', risk: '#ef4444', sentiment: '#ec4899',
    monte_carlo: '#a855f7', recommendation: '#10b981', default: '#64748b',
  };

  return (
    <div className="overflow-x-auto" data-testid="sim-dag">
      <svg width={svgW} height={svgH}>
        {edges.map((e, i) => {
          const from = positions[e.from]; const to = positions[e.to];
          if (!from || !to) return null;
          return <line key={i} x1={from.x + nw} y1={from.y + nh / 2} x2={to.x} y2={to.y + nh / 2}
            stroke="#334155" strokeWidth={1.2} markerEnd="url(#sim-arrow)" />;
        })}
        <defs><marker id="sim-arrow" markerWidth="7" markerHeight="5" refX="7" refY="2.5" orient="auto">
          <polygon points="0 0,7 2.5,0 5" fill="#475569" />
        </marker></defs>
        {nodes.map(n => {
          const pos = positions[n.id];
          if (!pos) return null;
          const c = colors[n.type] || colors.default;
          return (
            <g key={n.id}>
              <rect x={pos.x} y={pos.y} width={nw} height={nh} rx={6} fill={c + '20'} stroke={c} strokeWidth={1.5} />
              <text x={pos.x + nw / 2} y={pos.y + nh / 2 + 4} textAnchor="middle" fill="#e2e8f0" fontSize={9} fontWeight={500}>
                {n.label.length > 20 ? n.label.slice(0, 18) + '…' : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────

export default function SimulationsPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [selectedContract, setSelectedContract] = useState<string>('portfolio');
  const [simType, setSimType] = useState<SimType>('full_stress_test');
  const [params, setParams] = useState<Record<string, any>>({
    location: 'Northern Europe',
    period_months: 12,
    weather_params: ['solar_irradiance', 'wind_speed', 'temperature'],
    price_variation_pct: 20,
    price_steps: 5,
    discount_rate: 7,
    iterations: 1000,
    confidence_level: 95,
    news_headlines_text: '',
  });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SimResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<SimResult[]>([]);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetch(`${API_URL}/api/contractiq/contracts?limit=50`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.json()).then(d => setContracts(d.data || [])).catch(() => {});
  }, []);

  const runSimulation = useCallback(async () => {
    setRunning(true); setError(null); setResult(null);
    const token = getToken();
    if (!token) { setError('Not authenticated'); setRunning(false); return; }

    const newsLines = (params.news_headlines_text || '').split('\n').filter((l: string) => l.trim());

    const res = await apiFetch<any>(`${API_URL}/api/contractiq/simulate`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        simulation_type: simType,
        contract_id: selectedContract === 'portfolio' ? null : selectedContract,
        parameters: { ...params, news_headlines_text: undefined },
        news_headlines: newsLines,
      }),
    });
    if (!res.ok) {
      setError(res.error || 'Simulation failed');
    } else if (res.data?.data) {
      setResult(res.data.data);
      setHistory(prev => [res.data.data, ...prev].slice(0, 10));
    }
    setRunning(false);
  }, [simType, selectedContract, params]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="max-w-7xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/20 flex items-center justify-center">
              <Gauge className="w-5 h-5 text-emerald-400" />
            </div>
            Market Simulation & Stress Test
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Run weather, price, sentiment, and Monte Carlo simulations on your contract portfolio
          </p>
        </div>
        {history.length > 0 && (
          <span className="text-[10px] text-slate-500">{history.length} simulation{history.length > 1 ? 's' : ''} this session</span>
        )}
      </div>

      <PageExplainer routeKey="simulations" />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Controls */}
        <div className="lg:col-span-1 space-y-4">
          {/* Scope selector */}
          <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Simulation Scope</p>
            <select
              value={selectedContract}
              onChange={e => setSelectedContract(e.target.value)}
              data-testid="sim-scope"
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white"
            >
              <option value="portfolio">Entire Portfolio ({contracts.length} contracts)</option>
              {contracts.map(c => (
                <option key={c.id} value={c.id}>{c.title} ({c.contract_type})</option>
              ))}
            </select>
          </div>

          {/* Simulation type selector */}
          <div className="space-y-2">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">Simulation Type</p>
            <div className="grid grid-cols-1 gap-2">
              {SIM_TYPES.map(s => (
                <SimTypeCard key={s.id} sim={s} selected={simType === s.id} onClick={() => setSimType(s.id)} />
              ))}
            </div>
          </div>

          {/* Parameter controls */}
          <ParameterPanel simType={simType} params={params} onChange={setParams} />

          {/* Run button */}
          <button
            onClick={runSimulation}
            disabled={running}
            data-testid="sim-run"
            className="w-full py-3 rounded-xl bg-gradient-to-r from-emerald-500 to-cyan-500 text-white font-medium text-sm hover:from-emerald-400 hover:to-cyan-400 disabled:opacity-50 transition-all shadow-lg shadow-emerald-500/20 flex items-center justify-center gap-2"
          >
            {running ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> Running simulation...</>
            ) : (
              <><Play className="w-4 h-4" /> Run {SIM_TYPES.find(s => s.id === simType)?.label}</>
            )}
          </button>

          {error && (
            <div className="flex items-start gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/20 rounded-lg p-3">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {error}
            </div>
          )}
        </div>

        {/* Right: Results */}
        <div className="lg:col-span-2">
          {running && (
            <div className="flex flex-col items-center justify-center py-20">
              <div className="relative">
                <div className="w-16 h-16 border-4 border-emerald-500/20 border-t-emerald-500 rounded-full animate-spin" />
                <Gauge className="w-6 h-6 text-emerald-400 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
              </div>
              <p className="text-sm text-slate-400 mt-4">Running {SIM_TYPES.find(s => s.id === simType)?.label}...</p>
              <p className="text-[10px] text-slate-600 mt-1">The agent is calling weather, pricing, and risk tools</p>
            </div>
          )}

          {!running && !result && (
            <div className="flex flex-col items-center justify-center py-20" data-testid="sim-empty">
              <Gauge className="w-12 h-12 text-slate-700 mb-4" />
              <p className="text-sm text-slate-500 mb-1">No simulation results yet</p>
              <p className="text-[10px] text-slate-600">Select a simulation type, adjust parameters, and click Run</p>
            </div>
          )}

          {!running && result && <ResultsPanel result={result} />}
        </div>
      </div>
    </motion.div>
  );
}
