import type { MetricValue } from './types';

export type ValueKind = 'boolean' | 'number' | 'integer' | 'json' | 'choice' | 'text';

export interface WritableMetric {
  name: string;
  label: string;
  help: string;
  kind: ValueKind;
  datatype: string;
  choices?: { value: string; label: string }[];
  // what happens on the machine, said in the confirmation
  effect?: (v: MetricValue) => string;
}

export const WRITABLE: WritableMetric[] = [
  {
    name: 'Safety/Hold', label: 'Safety hold', kind: 'boolean', datatype: 'Boolean',
    help: 'On stops the machine where it is and keeps it stopped. Off lets it carry on.',
    effect: (v) => (v ? 'The machine stops where it is and stays stopped until the hold is turned off.' : 'The hold is released and the machine may move again.'),
  },
  {
    name: 'Mode/Set', label: 'Mode', kind: 'choice', datatype: 'String',
    help: 'Auto runs its tasks, hold pauses it, safe parks it in its safe state.',
    choices: [
      { value: 'auto', label: 'auto, run assigned tasks' },
      { value: 'hold', label: 'hold, pause where it is' },
      { value: 'safe', label: 'safe, park in the safe state' },
    ],
    effect: (v) => (v === 'auto' ? 'The machine starts running its assigned tasks.' : v === 'hold' ? 'The machine pauses where it is.' : 'The machine parks in its safe state.'),
  },
  {
    name: 'Task/Assign', label: 'Assign a task', kind: 'json', datatype: 'String',
    help: 'The task as JSON, for example {"task": "dig", "zone": "A3"}. The machine starts it when it is in auto.',
    effect: () => 'The machine takes this task and starts it when it is in auto mode.',
  },
];

const NUMERIC = /^(u?int(8|16|32|64)|float|double)$/i;

export function kindFor(datatype: string | undefined, value: MetricValue): ValueKind {
  const d = (datatype || '').toLowerCase();
  if (d === 'boolean' || typeof value === 'boolean') return 'boolean';
  if (/^u?int/.test(d)) return 'integer';
  if (NUMERIC.test(d) || typeof value === 'number') return 'number';
  return 'text';
}

export function datatypeFor(kind: ValueKind, given?: string): string {
  if (given) return given;
  return kind === 'boolean' ? 'Boolean' : kind === 'integer' ? 'Int64' : kind === 'number' ? 'Double' : 'String';
}

export function parseValue(kind: ValueKind, raw: string, choices?: { value: string }[]): { value: MetricValue; problem: string | null } {
  const v = raw.trim();
  if (kind === 'boolean') {
    if (v === 'true' || v === 'false') return { value: v === 'true', problem: null };
    return { value: null, problem: 'Pick on or off.' };
  }
  if (kind === 'choice') {
    if (choices?.some((c) => c.value === v)) return { value: v, problem: null };
    return { value: null, problem: 'Pick one of the options.' };
  }
  if (kind === 'number' || kind === 'integer') {
    if (!v) return { value: null, problem: 'Enter a number.' };
    const n = Number(v);
    if (!Number.isFinite(n)) return { value: null, problem: `"${v}" is not a number. Use digits, with a dot for decimals.` };
    if (kind === 'integer' && !Number.isInteger(n)) return { value: null, problem: 'This metric takes whole numbers only.' };
    return { value: n, problem: null };
  }
  if (kind === 'json') {
    if (!v) return { value: null, problem: 'Enter the task as JSON, for example {"task": "dig", "zone": "A3"}.' };
    try {
      const parsed = JSON.parse(v);
      if (!parsed || typeof parsed !== 'object') return { value: null, problem: 'The task must be a JSON object, in curly brackets.' };
      return { value: JSON.stringify(parsed), problem: null };
    } catch {
      return { value: null, problem: 'That is not valid JSON. Check the quotes and brackets.' };
    }
  }
  if (!v) return { value: null, problem: 'Enter a value.' };
  return { value: v, problem: null };
}

export function commandTopic(group: string, node: string, device: string): string {
  return device ? `spBv1.0/${group}/DCMD/${node}/${device}` : `spBv1.0/${group}/NCMD/${node}`;
}

// the Sparkplug B payload as it goes on the wire, written out as JSON for the preview
export function commandPreview(p: { group: string; node: string; device: string; metric: string; datatype: string; value: MetricValue }, now = Date.now()): { topic: string; payload: string; kind: 'DCMD' | 'NCMD' } {
  return {
    kind: p.device ? 'DCMD' : 'NCMD',
    topic: commandTopic(p.group, p.node, p.device),
    payload: JSON.stringify({ timestamp: now, metrics: [{ name: p.metric, timestamp: now, datatype: p.datatype, value: p.value }] }, null, 2),
  };
}
