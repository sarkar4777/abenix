'use client';

import { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { TIER_STYLE, type Tier } from './TierPolicies';

const ORDER: Tier[] = ['critical', 'high', 'medium', 'low'];

export default function ToolTiers({ tools }: { tools: { tool: string; tier: string }[] }) {
  const [q, setQ] = useState('');
  const [only, setOnly] = useState<Tier | 'all'>('all');

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    tools.forEach((t) => (c[t.tier] = (c[t.tier] || 0) + 1));
    return c;
  }, [tools]);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return ORDER.filter((t) => only === 'all' || only === t)
      .map((tier) => ({
        tier,
        items: tools.filter((t) => t.tier === tier && (!needle || t.tool.toLowerCase().includes(needle))),
      }))
      .filter((g) => g.items.length > 0);
  }, [tools, q, only]);

  return (
    <div className="space-y-5" data-testid="tool-tiers">
      <p className="text-sm text-slate-400 max-w-3xl">
        Each tool declares its own tier, set by whoever built it. A run that calls a tool above its own tier follows the
        policy for the tool&apos;s tier. To let an agent use a riskier tool without asking, raise the agent&apos;s tier in
        the agent builder.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 w-full sm:w-72">
          <Search className="w-4 h-4 text-slate-500" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`Search ${tools.length} tools…`}
            className="flex-1 bg-transparent py-2 text-sm text-white outline-none"
            aria-label="Search tools"
            data-testid="tool-tiers-search"
          />
        </div>
        {(['all', ...ORDER] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setOnly(t)}
            aria-pressed={only === t}
            className={`px-2.5 py-1 rounded-md text-xs border ${
              only === t ? 'border-cyan-500/60 bg-cyan-500/10 text-white' : 'border-slate-700 text-slate-400 hover:text-white'
            }`}
          >
            {t === 'all' ? `All ${tools.length}` : `${TIER_STYLE[t].label} ${counts[t] || 0}`}
          </button>
        ))}
      </div>
      {groups.length === 0 ? (
        <p className="text-sm text-slate-500">No tool matches {q ? `“${q}”` : 'this filter'}.</p>
      ) : (
        groups.map((g) => (
          <section key={g.tier} aria-label={`${g.tier} risk tools`}>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-white mb-2">
              <span className={`w-2 h-2 rounded-full ${TIER_STYLE[g.tier].dot}`} aria-hidden />
              {TIER_STYLE[g.tier].label} risk <span className="text-slate-500 font-normal">({g.items.length})</span>
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {g.items.map((t) => (
                <span
                  key={t.tool}
                  className={`text-xs font-mono px-2 py-1 rounded border ${TIER_STYLE[g.tier].chip}`}
                  data-testid={`tool-tier-${t.tool}`}
                >
                  {t.tool}
                </span>
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}
