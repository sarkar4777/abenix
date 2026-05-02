import { Headphones, Construction } from 'lucide-react';

export default function LiveConsole() {
  return (
    <div className="p-8 max-w-5xl mx-auto">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · phase-2 preview</p>
      <h1 className="text-2xl font-bold text-white flex items-center gap-2">
        <Headphones className="w-5 h-5 text-cyan-400" /> Live Agent Console
      </h1>
      <p className="text-sm text-slate-400 mt-1">
        Agent-assist copilot — will stream next-sentence suggestions, refund
        ceilings, and cited policies in real time while a human CSM types.
      </p>

      <div
        className="mt-6 rounded-xl border border-amber-500/30 bg-amber-500/5 p-6"
        data-testid="live-console-stub"
      >
        <div className="flex items-start gap-3">
          <Construction className="w-5 h-5 text-amber-300 shrink-0 mt-0.5" />
          <div className="space-y-3 text-sm">
            <p className="text-amber-200 font-semibold">Coming in Phase 2 — preview only</p>
            <p className="text-slate-300 leading-relaxed">
              The SSE stream at{' '}
              <code className="text-cyan-300">/api/resolveai/live-console/stream</code>{' '}
              is not wired up yet. Once Phase 2 lands you&apos;ll see token-by-token
              suggestions, citation chips, and a refund ceiling indicator update
              live as the human types — backed by the Live Copilot agent.
            </p>
            <p className="text-slate-400 text-xs">
              Until then, every other surface (Dashboard, Cases, SLA, QA, Trends, Admin)
              is fully functional and runs end-to-end against the deployed Abenix cluster.
            </p>
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-slate-700/50 bg-slate-800/30 p-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Planned UI</p>
        <ul className="text-xs text-slate-400 space-y-1.5 list-disc list-inside">
          <li>Streaming suggestion bar above the agent reply box.</li>
          <li>Live policy citation chips that mirror /cases/[id] styling.</li>
          <li>Refund / discount ceiling indicator from approval_tiers.</li>
          <li>Inline take-over button if confidence drops below 0.6.</li>
        </ul>
      </div>
    </div>
  );
}
