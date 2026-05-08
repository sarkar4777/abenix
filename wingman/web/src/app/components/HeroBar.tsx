'use client';

import { ReactNode, useEffect, useState } from 'react';
import { Activity, Wifi } from 'lucide-react';

interface BriefIndicator {
  label: string;
  unit: string;
  latest: number | null;
  wow_change_pct: number | null;
  source?: string;
}

interface MarketBrief {
  indicators?: BriefIndicator[];
  data_quality?: string;
}

/**
 * Page hero — gradient title, optional eyebrow, optional inline tickers from
 * the market-brief endpoint. Designed so every Wingman page opens with
 * something live and trader-y at the top.
 */
export default function HeroBar({
  eyebrow,
  title,
  subtitle,
  rightSlot,
  showTickers = true,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  rightSlot?: ReactNode;
  showTickers?: boolean;
}) {
  const [brief, setBrief] = useState<MarketBrief | null>(null);

  useEffect(() => {
    if (!showTickers) return;
    let cancelled = false;
    const load = () => {
      fetch('/api/wingman/market-brief')
        .then((r) => r.json())
        .then((j) => { if (!cancelled) setBrief(j.data || null); })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(t); };
  }, [showTickers]);

  const tickers = (brief?.indicators || []).slice(0, 4);

  return (
    <header className="mb-6 relative">
      <div className="flex items-end justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && (
            <div className="text-[10px] uppercase tracking-[0.25em] text-emerald-300/80 font-bold mb-1.5">
              {eyebrow}
            </div>
          )}
          <h1 className="text-3xl md:text-4xl font-bold tracking-tight bg-gradient-to-r from-white via-emerald-50 to-cyan-100 bg-clip-text text-transparent">
            {title}
          </h1>
          {subtitle && (
            <p className="text-sm text-slate-400 mt-1.5 max-w-2xl">{subtitle}</p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {rightSlot}
        </div>
      </div>

      {showTickers && tickers.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-[10px]">
          <span className="inline-flex items-center gap-1 text-emerald-300/80 uppercase tracking-wider font-semibold">
            <Wifi className="w-3 h-3 animate-pulse" /> live
          </span>
          {tickers.map((t, i) => {
            const wow = t.wow_change_pct;
            const wowPos = wow != null && wow >= 0;
            return (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-slate-800 bg-slate-900/50 backdrop-blur"
                title={t.source}
              >
                <span className="text-slate-500">{t.label.replace(/^Live LPG\/tanker AIS$/, 'LPG vessels')}</span>
                <span className="text-white font-mono font-semibold">
                  {t.latest != null
                    ? Number(t.latest).toFixed(t.unit === '$/gal' ? 3 : t.unit === 'vessels' ? 0 : 2)
                    : '—'}
                </span>
                <span className="text-slate-600">{t.unit}</span>
                {wow != null && (
                  <span className={`font-mono ${wowPos ? 'text-emerald-300' : 'text-rose-300'}`}>
                    {wowPos ? '+' : ''}{wow.toFixed(1)}%
                  </span>
                )}
              </span>
            );
          })}
        </div>
      )}
    </header>
  );
}
