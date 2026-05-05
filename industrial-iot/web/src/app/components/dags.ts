import type { DagDef } from './PipelineDagViz';

export const VALUEEDGE_DAG: DagDef = {
  title: 'Design Studio — Engineering & EPC copilot',
  pipelineSlug: 'iot-valueedge-pipeline',
  description:
    'A site brief flows through a 9-node DAG: validate → configure 3 design scenarios → recompute deterministic costs → run VE optimisation and compliance checking in parallel → conditional RFI drafting only if blocker findings exist → assemble the final report.',
  nodes: [
    { id: 'validate',          label: 'Validate input',     kind: 'inline', description: 'Sanity-check site brief shape' },
    { id: 'configure',         label: 'Configure scenarios',kind: 'agent',  description: 'iot-valueedge-scenario-configurator — 3 ranked layouts grounded in IEC 61400-3 + RWE EPC standards' },
    { id: 'cost',              label: 'Cost recompute',     kind: 'inline', description: 'Deterministic CapEx + LCOE replacing the agent\'s rule-of-thumb numbers' },
    { id: 've',                label: 'VE optimisation',    kind: 'agent',  description: 'iot-valueedge-ve-optimizer — Pareto-ranked value-engineering opportunities' },
    { id: 'compliance',        label: 'Compliance check',   kind: 'agent',  description: 'iot-valueedge-compliance-checker — flags IEC/NEC/IEEE/RWE-EPC clause violations' },
    { id: 'rfi_router',        label: 'RFI router',         kind: 'switch', description: 'Routes blocker / major findings to the RFI drafter' },
    { id: 'rfi',               label: 'Draft RFIs',         kind: 'agent',  description: 'iot-valueedge-rfi-drafter — formal RFI text with cited evidence' },
    { id: 'final',             label: 'Final report',       kind: 'final',  description: 'Scenarios + VE + compliance + RFIs assembled for the UI' },
  ],
  edges: [
    { from: 'validate',   to: 'configure'   },
    { from: 'configure',  to: 'cost'        },
    { from: 'cost',       to: 've'          },
    { from: 'cost',       to: 'compliance'  },
    { from: 've',         to: 'rfi_router'  },
    { from: 'compliance', to: 'rfi_router'  },
    { from: 'rfi_router', to: 'rfi',        condition: 'blocker/major' },
    { from: 've',         to: 'final'       },
    { from: 'compliance', to: 'final'       },
    { from: 'rfi',        to: 'final'       },
  ],
};

export const FIELDEDGE_DAG: DagDef = {
  title: 'Field Guide — Wind-farm maintenance copilot',
  pipelineSlug: 'iot-fieldedge-pipeline',
  description:
    'A technician\'s voice/text query is validated, fanned out to fleet-history search and the troubleshoot assistant in parallel, then merged into a procedure with cited manual sections + similar past WOs.',
  nodes: [
    { id: 'validate',     label: 'Validate query',    kind: 'inline', description: 'Pull turbine context (model, install date, last service) from fleet.json' },
    { id: 'fleet',        label: 'Fleet history',     kind: 'agent',  description: 'iot-fieldedge-fleet-history-searcher — finds similar past WOs across the 12-turbine fleet' },
    { id: 'trouble',      label: 'Troubleshoot',      kind: 'agent',  description: 'iot-fieldedge-troubleshoot-assistant — KB-grounded procedure + safety warnings + cited manual sections' },
    { id: 'final',        label: 'Final response',    kind: 'final',  description: 'Procedure + parts list + similar WOs + safety gate' },
  ],
  edges: [
    { from: 'validate', to: 'fleet'   },
    { from: 'validate', to: 'trouble' },
    { from: 'fleet',    to: 'final'   },
    { from: 'trouble',  to: 'final'   },
  ],
};

export const BEDROCC_DAG: DagDef = {
  title: 'Alarm Desk — Operations control-room triage',
  pipelineSlug: 'iot-bedrocc-pipeline',
  description:
    'A SCADA alarm is validated, classified for severity + ROI in parallel with cascade-correlation, then routed: only nominated safe-reset candidates with non-CRIT severity reach the safe-reset advisor, which enforces a 4-stage gate before recommending a command.',
  nodes: [
    { id: 'validate',   label: 'Validate alarm',     kind: 'inline', description: 'Resolve asset hierarchy (Site → Turbine → Subsystem) for the incoming alarm code' },
    { id: 'classify',   label: 'Classify',           kind: 'agent',  description: 'iot-bedrocc-alarm-classifier — severity + root-cause hypothesis + confidence + ROI estimate' },
    { id: 'noise',      label: 'Cascade filter',     kind: 'agent',  description: 'iot-bedrocc-noise-filter — suppresses correlated cascade members; never suppresses safety-prefixed codes' },
    { id: 'reset_router', label: 'Reset router',     kind: 'switch', description: 'Routes nominated-reset + non-CRIT alarms to the safe-reset advisor' },
    { id: 'safe_reset', label: 'Safe-reset advisor', kind: 'agent',  description: 'iot-bedrocc-safe-reset-advisor — 4-stage gate (hard gates → authority → context preconds → minimum-privilege command)' },
    { id: 'final',      label: 'Triage envelope',    kind: 'final',  description: 'Classification + cascade context + reset recommendation (or DENY) for the operator UI' },
  ],
  edges: [
    { from: 'validate',     to: 'classify'    },
    { from: 'validate',     to: 'noise'       },
    { from: 'classify',     to: 'reset_router'},
    { from: 'noise',        to: 'reset_router'},
    { from: 'reset_router', to: 'safe_reset', condition: 'safe_remote_reset && severity !== CRIT' },
    { from: 'classify',     to: 'final'       },
    { from: 'noise',        to: 'final'       },
    { from: 'safe_reset',   to: 'final'       },
  ],
};
