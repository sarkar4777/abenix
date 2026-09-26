'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, TrendingUp } from 'lucide-react';

type Pair = {
  drug: string; pt: string; cases: number; serious: number;
  prr: number | null; eb05: number | null; signal: boolean;
};

export default function Signals() {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch('/api/pv/signals', { cache: 'no-store' });
        const body = await r.json();
        setPairs((body?.data ?? []) as Pair[]);
      } catch {
        /* transient */
      } finally {
        setLoaded(true);
      }
    };
    void load();
    const t = setInterval(() => void load(), 8000);
    return () => clearInterval(t);
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 text-slate-200">
      <header className="border-b border-slate-800/80 bg-slate-900/40">
        <div className="mx-auto max-w-5xl px-6 py-4 flex items-center gap-3">
          <a href="/" className="text-slate-500 hover:text-teal-300"><ArrowLeft className="w-4 h-4" /></a>
          <div>
            <h1 className="text-base font-bold text-white">Signal board</h1>
            <p className="text-[11px] text-slate-500">
              Drug-event pairs across the case history, strongest disproportionality first
            </p>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-6 space-y-4">
        <div className="rounded-lg bg-slate-900/60 ring-1 ring-slate-800 px-4 py-3 text-xs text-slate-400 leading-relaxed">
          <strong className="text-slate-300">How to read this.</strong> PRR and EB05
          measure how often a pair is reported relative to the rest of the database.
          They are computed in closed form by the disproportionality code asset, not
          estimated by a model. A pair with fewer than three reports is never called
          a signal however large its ratio, because the ratio is not stable at that
          count. None of this is evidence of causality — for that, read the case.
        </div>

        <div className="rounded-xl bg-slate-900/60 ring-1 ring-slate-800 overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-800 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-white">Pairs</h3>
            <span className="text-xs text-slate-500">({pairs.length})</span>
          </div>
          {!loaded ? (
            <p className="px-4 py-10 text-center text-sm text-slate-500">Loading…</p>
          ) : pairs.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-slate-500">
              No assessed pairs yet. File a few cases and they will appear here.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 text-left border-b border-slate-800">
                    <th className="px-4 py-2 font-medium">Drug</th>
                    <th className="px-4 py-2 font-medium">Preferred term</th>
                    <th className="px-4 py-2 font-medium text-right">Cases</th>
                    <th className="px-4 py-2 font-medium text-right">Serious</th>
                    <th className="px-4 py-2 font-medium text-right">PRR</th>
                    <th className="px-4 py-2 font-medium text-right">EB05</th>
                    <th className="px-4 py-2 font-medium">Signal</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {pairs.map((p, i) => (
                    <tr key={i} data-testid={`pair-${i}`} className="hover:bg-slate-800/30">
                      <td className="px-4 py-2 text-white">{p.drug}</td>
                      <td className="px-4 py-2 text-slate-300">{p.pt}</td>
                      <td className="px-4 py-2 text-right text-slate-400">{p.cases}</td>
                      <td className="px-4 py-2 text-right text-slate-400">{p.serious}</td>
                      <td className="px-4 py-2 text-right text-slate-300">
                        {p.prr !== null ? p.prr.toFixed(2) : '—'}
                      </td>
                      <td className="px-4 py-2 text-right text-slate-300">
                        {p.eb05 !== null ? p.eb05.toFixed(2) : '—'}
                      </td>
                      <td className="px-4 py-2">
                        {p.signal ? (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-300 ring-1 ring-violet-500/30">
                            signal
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
