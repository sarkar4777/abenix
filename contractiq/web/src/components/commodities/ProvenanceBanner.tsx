'use client';

export type ProvenanceMode = 'real_fetched' | 'agent_simulated' | 'mixed' | string;

export interface Provenance {
  data_source?: string;
  last_refresh?: string;
  mode?: ProvenanceMode;
  notes?: string;
}

const MODE_LABEL: Record<string, string> = {
  real_fetched: 'real fetched',
  agent_simulated: 'agent-simulated · calibrated to public realized vol',
  mixed: 'mixed · partial live + calibrated',
};

const MODE_TONE: Record<string, string> = {
  real_fetched: 'bg-emerald-500/10 text-emerald-200 border-emerald-500/30',
  agent_simulated: 'bg-amber-500/10 text-amber-200 border-amber-500/30',
  mixed: 'bg-sky-500/10 text-sky-200 border-sky-500/30',
};

interface Props {
  provenance?: Provenance | null;
  // True when the runtime canonical-anchor guardrail overrode the agent's
  // output. Drives the amber "agent output corrected" pill so analysts
  // know the numbers in front of them are NOT what the model produced.
  postProcessed?: boolean;
}

export function ProvenanceBanner({ provenance, postProcessed }: Props) {
  const mode = provenance?.mode || 'agent_simulated';
  const label = MODE_LABEL[mode] || mode;
  const tone = MODE_TONE[mode] || MODE_TONE.agent_simulated;
  return (
    <div
      data-testid="provenance-banner"
      className={`rounded-lg border px-4 py-3 text-xs flex flex-wrap items-center gap-x-4 gap-y-1 ${tone}`}
    >
      <span className="font-semibold uppercase tracking-wider text-[10px]">Provenance</span>
      <span data-testid="provenance-mode">{label}</span>
      {postProcessed && (
        <span
          data-testid="guardrail-corrected-pill"
          title="The agent's claimed fallback was overridden because live TTF data was actually fetched"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-amber-400/60 bg-amber-400/15 text-amber-100 text-[10px] font-semibold uppercase tracking-wider cursor-help"
        >
          agent output corrected by runtime guardrail
        </span>
      )}
      {provenance?.data_source && (
        <span data-testid="provenance-source" className="opacity-90">
          source: {provenance.data_source}
        </span>
      )}
      {provenance?.last_refresh && (
        <span data-testid="provenance-refresh" className="opacity-80">
          refreshed: {provenance.last_refresh}
        </span>
      )}
      {provenance?.notes && <span className="opacity-70">· {provenance.notes}</span>}
    </div>
  );
}

export default ProvenanceBanner;
