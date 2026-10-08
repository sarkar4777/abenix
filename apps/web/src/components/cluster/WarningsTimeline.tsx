'use client';

import { useState } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { agoText, type ClusterEvent } from '@/lib/cluster';

export default function WarningsTimeline({
  events, onWorkload, eventsHidden,
}: { events: ClusterEvent[]; onWorkload: (name: string) => void; eventsHidden?: string | null }) {
  const [all, setAll] = useState(false);
  if (eventsHidden) {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-xs text-amber-200" data-testid="warnings-hidden">
        {eventsHidden}
      </div>
    );
  }
  if (!events.length) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center" data-testid="warnings-empty">
        <CheckCircle2 className="w-6 h-6 text-emerald-400 mx-auto mb-2" />
        <div className="text-sm text-slate-300">No warnings in the last hour</div>
        <div className="text-xs text-slate-500 mt-1">Failed probes, crashes, scheduling trouble and pull errors show up here.</div>
      </div>
    );
  }
  const shown = all ? events : events.slice(0, 12);
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-4" data-testid="warnings-timeline">
      <ol className="relative border-l border-slate-700/70 ml-1.5 space-y-3">
        {shown.map((e, i) => (
          <li key={`${e.at}-${i}`} className="pl-4 relative" data-testid="warning-item">
            <span className="absolute -left-[5px] top-1.5 w-2.5 h-2.5 rounded-full bg-amber-400 ring-4 ring-slate-950" />
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
              <span className="font-medium text-amber-300">{e.reason}</span>
              {e.count > 1 && <span className="text-slate-500">×{e.count}</span>}
              {(e.objects ?? 1) > 1 && <span className="text-slate-500">on {e.objects} pods</span>}
              <span className="text-slate-500">{agoText(e.age_seconds)}</span>
              {e.workload ? (
                <button
                  type="button"
                  onClick={() => onWorkload(e.workload as string)}
                  className="text-cyan-300 hover:underline break-all text-left"
                  title="Show this service"
                >
                  {e.workload}
                </button>
              ) : (
                <span className="text-slate-400 break-all">{e.kind} {e.object}</span>
              )}
            </div>
            <div className="text-xs text-slate-400 mt-0.5 break-words">{e.message}</div>
          </li>
        ))}
      </ol>
      {events.length > 12 && (
        <button type="button" onClick={() => setAll((a) => !a)} className="mt-3 text-xs text-cyan-300 hover:underline">
          {all ? 'Show fewer' : `Show all ${events.length}`}
        </button>
      )}
    </div>
  );
}
