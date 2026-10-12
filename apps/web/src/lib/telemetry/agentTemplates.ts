// Starting points for agents that read streams and act on assets, used from Telemetry and the builder

import { blankPolicy, type CommandPolicy } from './commandPolicy';
import { agentAssetLabel } from './assetLabel';

export type TemplateId = 'machine-health-watcher' | 'fleet-dispatcher' | 'anomaly-triage' | 'shift-reporter';

export interface TemplateAsset {
  key: string;
  name?: string;
}

export interface AgentTemplate {
  id: TemplateId;
  name: string;
  blurb: string;
  when: string;
  tools: string[];
  commands: boolean;
  output: string;
  prompt: (asset?: TemplateAsset) => string;
  description: (asset?: TemplateAsset) => string;
  examples: (asset?: TemplateAsset) => string[];
}

const ANSWER = 'End your answer with one JSON object, and nothing after it';

function about(a?: TemplateAsset): string {
  return a ? `${a.name || a.key} (key ${a.key})` : 'the asset named in the message';
}

export const AGENT_TEMPLATES: AgentTemplate[] = [
  {
    id: 'machine-health-watcher',
    name: 'Machine health watcher',
    blurb: 'Reads a machine when a rule fires, judges whether it is healthy and proposes a safe command when it is not.',
    when: 'Run it from a rule on a pressure, temperature or fault signal.',
    tools: ['asset_search', 'device_state', 'signal_history', 'device_command'],
    commands: true,
    output: '{"healthy": bool, "severity": "ok|watch|act", "finding": "...", "action": "none|<signal>=<value>", "command_sent": bool}',
    prompt: (a) => `You watch the health of ${about(a)}.

When you are started, the message says which rule fired, on which asset and signal, and the recent trend. The full firing is in your context under telemetry.

1. Call device_state for the asset to see every reading now, and whether it is online.
2. Call signal_history on the signal that fired, and on one or two related signals, over the last hour, to see the trend.
3. Decide: is the machine healthy, worth watching, or does it need an action now. Say what you saw, with the numbers and times.
4. Only when it needs an action, call device_command with the asset, the signal and a safe value, and a one sentence reason that cites the readings. A person may have to approve it, the call waits and tells you who decided. Never say a command was sent unless device_command says published.

${ANSWER}: {"healthy": true|false, "severity": "ok"|"watch"|"act", "finding": "what you saw", "action": "none" or "Signal=value", "command_sent": true|false}`,
    description: (a) => `Watches ${a ? a.name || a.key : 'a machine'} when a signal rule fires and proposes a safe command when it is not healthy.`,
    examples: (a) => [
      `Check ${a ? a.name || a.key : 'the excavator'} now and tell me if it is healthy.`,
      'Look at the last hour of the signal that fired and say whether it is still rising.',
    ],
  },
  {
    id: 'fleet-dispatcher',
    name: 'Fleet dispatcher',
    blurb: 'Finds vehicles by type or tag, reads where they are and what they do, and assigns the next task.',
    when: 'Run it from a rule like a truck leaving its route, or on a schedule.',
    tools: ['asset_search', 'device_state', 'device_command'],
    commands: true,
    output: '{"vehicles": n, "assignments": [{"asset": "...", "task": "...", "sent": bool}], "notes": "..."}',
    prompt: (a) => `You dispatch a fleet${a ? `, starting from ${about(a)}` : ''}.

1. Call asset_search with type vehicle, or the tag in the message, and online true, to find the vehicles.
2. Call device_state with assets set to their keys and a metrics filter for position, speed and task signals, so you read them all at once.
3. Decide which vehicle should do what next. Prefer the closest idle one, and say why with the numbers.
4. To assign a task, call device_command on that vehicle with the task signal and value, and a reason. It may wait for a person to approve. Never say a task was assigned unless device_command says published.

${ANSWER}: {"vehicles": number seen, "assignments": [{"asset": "key", "task": "value", "sent": true|false}], "notes": "anything a dispatcher should know"}`,
    description: (a) => `Assigns tasks to vehicles${a ? ` around ${a.name || a.key}` : ''} from their live position and state.`,
    examples: () => ['Which haul trucks are idle right now, and where?', 'Assign the closest idle truck to the north pit.'],
  },
  {
    id: 'anomaly-triage',
    name: 'Anomaly triage',
    blurb: 'Decides whether a firing is real, how serious it is and the likely cause, without touching anything.',
    when: 'Put it first in a rule, and let later steps act on its answer.',
    tools: ['asset_search', 'device_state', 'signal_history'],
    commands: false,
    output: '{"real": bool, "severity": "low|medium|high", "cause": "...", "next_step": "..."}',
    prompt: (a) => `You triage anomalies on ${about(a)}. You never change anything, you only read and judge.

1. Read the firing in the message: the rule, the signal, the value and the trend.
2. Call signal_history on that signal over the last few hours, and device_state for the asset now.
3. Judge whether it is a real problem or noise: a stuck sensor, a gap, a spike that already settled. Give the likely cause and the next step a person or a later rule step should take.

${ANSWER}: {"real": true|false, "severity": "low"|"medium"|"high", "cause": "likely cause", "next_step": "what to do next"}

A later step of the rule can read it as {steps.1.output.severity}.`,
    description: (a) => `Judges whether a signal rule firing${a ? ` on ${a.name || a.key}` : ''} is real, how serious it is and why.`,
    examples: () => ['Is the last pressure alarm real or a sensor glitch?'],
  },
  {
    id: 'shift-reporter',
    name: 'Shift reporter',
    blurb: 'Writes a plain shift summary for a group of assets: what ran, what stopped, what to watch.',
    when: 'Run it on a schedule at the end of each shift.',
    tools: ['asset_search', 'device_state', 'signal_history'],
    commands: false,
    output: '{"assets": n, "online": n, "highlights": ["..."], "watch": ["..."]}',
    prompt: (a) => `You write the shift report for ${a ? `${about(a)} and the assets around it` : 'the assets named in the message, or every asset in its group'}.

1. Call asset_search to list the assets, with their online state and a few readings.
2. Call signal_history with assets set to their keys over the last 8 hours for the signals that matter most, like speed, hours, fuel or pressure.
3. Write a short report a supervisor reads in a minute: what ran, what stopped and for how long, anything trending the wrong way. Use numbers and times.

${ANSWER}: {"assets": number, "online": number, "highlights": ["..."], "watch": ["..."]}`,
    description: (a) => `Writes a plain shift summary${a ? ` for ${a.name || a.key} and nearby assets` : ''}.`,
    examples: () => ['Write the report for the last 8 hours.'],
  },
];

export function templateById(id: string | null | undefined): AgentTemplate | null {
  return AGENT_TEMPLATES.find((t) => t.id === id) || null;
}

export interface TemplateBuild {
  name: string;
  description: string;
  system_prompt: string;
  tools: string[];
  tool_config: Record<string, { usage_instructions: string; parameter_defaults: Record<string, unknown>; max_calls: number; require_approval: boolean }>;
  example_prompts: string[];
}

/** The agent a template makes, for an asset when one is given. Commands always start with approval on. */
export function buildFromTemplate(t: AgentTemplate, asset?: TemplateAsset, signals: string[] = []): TemplateBuild {
  const tc: TemplateBuild['tool_config'] = {};
  if (t.commands) {
    const policy: CommandPolicy = {
      ...blankPolicy(),
      assets: asset ? [asset.key.split('/').filter(Boolean).slice(0, 2).join('/')] : [],
      signals,
      approval: 'always',
    };
    tc.device_command = {
      usage_instructions: 'Read device_state and signal_history first. Give a reason that cites the readings.',
      parameter_defaults: { policy },
      max_calls: 3,
      require_approval: false,
    };
  }
  const label = asset ? ` for ${agentAssetLabel(asset.key, asset.name)}` : '';
  return {
    name: `${t.name}${label}`.slice(0, 100),
    description: t.description(asset),
    system_prompt: t.prompt(asset),
    tools: t.tools,
    tool_config: tc,
    example_prompts: t.examples(asset),
  };
}

/** Where the builder opens with a template filled in, ready to save. */
export function templateHref(id: TemplateId, asset?: TemplateAsset): string {
  const q = new URLSearchParams({ template: id });
  if (asset) {
    q.set('asset', asset.key);
    if (asset.name) q.set('asset_name', asset.name);
  }
  return `/builder?${q.toString()}`;
}

// what the agent hands back, as words a person reads, not the JSON shape
export function answerWords(output: string): string {
  const keys = Array.from(output.matchAll(/"([a-z_]+)"\s*:/gi)).map((m) => m[1].replace(/_/g, ' '));
  const top = Array.from(new Set(keys)).slice(0, 5);
  if (!top.length) return 'Its answer is passed on, so later rule steps can use it.';
  const list = top.length > 1 ? `${top.slice(0, -1).join(', ')} and ${top[top.length - 1]}` : top[0];
  return `It answers with ${list}, so later rule steps can use them.`;
}
