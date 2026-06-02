'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ShieldCheck, ShieldAlert, ShieldX, AlertTriangle } from 'lucide-react';

interface CP {
  id: string;
  legal_name: string;
  ticker: string | null;
  sector: string | null;
  country: string | null;
  credit_rating: string | null;
  credit_score_1_100: number | null;
  risk_tier: 'green' | 'amber' | 'red' | 'unknown';
  credit_limit_usd: number | null;
  credit_utilisation_pct: number | null;
  last_kyc_at: string | null;
}

interface Resp {
  items: CP[];
  total: number;
  bands: { green: number; amber: number; red: number; unknown: number };
  avg_score: number;
}

const TIER_STYLE: Record<string, { ring: string; bg: string; text: string; bar: string; Icon: any; label: string }> = {
  green:   { ring: 'ring-emerald-500/40 hover:ring-emerald-400', bg: 'from-emerald-500/10 to-emerald-500/0', text: 'text-emerald-200', bar: 'bg-emerald-500',                Icon: ShieldCheck, label: 'LOW' },
  amber:   { ring: 'ring-amber-500/40 hover:ring-amber-400',     bg: 'from-amber-500/10 to-amber-500/0',     text: 'text-amber-200',   bar: 'bg-amber-500',                  Icon: ShieldAlert, label: 'MED' },
  red:     { ring: 'ring-rose-500/40 hover:ring-rose-400',       bg: 'from-rose-500/10 to-rose-500/0',       text: 'text-rose-200',    bar: 'bg-rose-500',                   Icon: ShieldX,     label: 'HIGH' },
  unknown: { ring: 'ring-slate-700 hover:ring-slate-500',        bg: 'from-slate-800/30 to-slate-800/0',     text: 'text-slate-300',   bar: 'bg-slate-500',                  Icon: AlertTriangle, label: 'N/A' },
};

function fmtUsd(v: number | null) {
  if (v === null) return '—';
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(1)}B`;
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(0)}M`;
  return `$${v.toLocaleString()}`;
}

export default function TrafficLightDashboard() {
  const [data, setData] = useState<Resp | null>(null);
  const [filter, setFilter] = useState<'all' | 'green' | 'amber' | 'red'>('all');

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const token = localStorage.getItem('contractiq_token') || '';
        const r = await fetch('/api/contractiq/counterparties', { headers: { Authorization: `Bearer ${token}` } });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setData(j?.data || null);
      } catch {}
    };
    fetchData();
    const t = setInterval(fetchData, 10000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!data) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6">
        <p className="text-xs text-slate-500">Loading counterparty heat map…</p>
      </div>
    );
  }

  const items = filter === 'all' ? data.items : data.items.filter(c => c.risk_tier === filter);

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-5" data-testid="traffic-light-dashboard">
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h2 className="text-base font-semibold text-white">Counterparty risk heat map</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">{data.total} counterparties · avg credit score {data.avg_score.toFixed(0)}/100 · click any card to drill in</p>
        </div>
        <div className="flex gap-1.5">
          {(['all', 'green', 'amber', 'red'] as const).map(f => {
            const count = f === 'all' ? data.total : data.bands[f];
            const isActive = filter === f;
            const tone = f === 'green' ? 'emerald' : f === 'amber' ? 'amber' : f === 'red' ? 'rose' : 'slate';
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-2.5 py-1 rounded-md text-[11px] border transition-colors ${
                  isActive
                    ? `bg-${tone}-500/15 text-${tone}-200 border-${tone}-500/40`
                    : 'bg-slate-900/40 text-slate-400 border-slate-800 hover:bg-slate-800/60'
                }`}
              >
                {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)} · {count}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {items.map(cp => {
          const t = TIER_STYLE[cp.risk_tier] || TIER_STYLE.unknown;
          const Ic = t.Icon;
          const score = cp.credit_score_1_100 ?? 0;
          const util = cp.credit_utilisation_pct ?? 0;
          return (
            <Link
              key={cp.id}
              href={`/credit-risk/counterparty/${cp.id}`}
              className={`group block rounded-xl border border-slate-800 bg-gradient-to-br ${t.bg} p-4 ring-1 ${t.ring} transition-all`}
              data-testid={`cp-card-${cp.risk_tier}`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Ic className={`w-4 h-4 ${t.text}`} />
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${t.text}`}>{t.label}</span>
                </div>
                {cp.credit_rating && <span className="text-[10px] text-slate-400 font-mono bg-slate-900/70 border border-slate-800 px-1.5 py-0.5 rounded">{cp.credit_rating}</span>}
              </div>
              <p className="text-sm font-semibold text-white truncate" title={cp.legal_name}>{cp.legal_name}</p>
              <p className="text-[10px] text-slate-500 truncate mt-0.5">{cp.sector ?? '—'}{cp.country ? ` · ${cp.country}` : ''}</p>
              <div className="mt-3">
                <div className="flex justify-between mb-1">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider">Credit score</span>
                  <span className={`text-xs font-mono font-bold ${t.text}`}>{score}/100</span>
                </div>
                <div className="h-1.5 bg-slate-800 rounded overflow-hidden">
                  <div className={`h-full ${t.bar}`} style={{ width: `${score}%` }} />
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
                <div>
                  <p className="text-slate-500 uppercase tracking-wider mb-0.5">Limit</p>
                  <p className="text-slate-200 font-mono">{fmtUsd(cp.credit_limit_usd)}</p>
                </div>
                <div>
                  <p className="text-slate-500 uppercase tracking-wider mb-0.5">Util</p>
                  <p className={`font-mono ${util > 80 ? 'text-rose-300' : util > 60 ? 'text-amber-300' : 'text-slate-200'}`}>{util.toFixed(0)}%</p>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {items.length === 0 && (
        <p className="text-xs text-slate-500 italic py-6 text-center">No counterparties in this tier.</p>
      )}
    </section>
  );
}
