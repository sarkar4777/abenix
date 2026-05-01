export default function LiveConsole() {
  return (
    <div className="p-8 max-w-5xl mx-auto">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">ResolveAI · phase-2</p>
      <h1 className="text-2xl font-bold text-white">Live Agent Console</h1>
      <p className="text-sm text-slate-400 mt-1">
        Agent-assist copilot surface — streams next-sentence suggestions, refund
        ceilings, and cited policies while the human CSM types.
      </p>
      <div className="mt-6 rounded-xl border border-dashed border-slate-700/60 bg-slate-800/20 p-10 text-center text-sm text-slate-500">
        Phase 2 — Live Agent Copilot streams from <code className="text-cyan-300">/api/resolveai/live-console/stream</code>.
      </div>
    </div>
  );
}
