// Signal rules: the shapes the API speaks, defaults, templates, client checks and plain words.

export type Severity = 'info' | 'warning' | 'critical';
export type CondKind = 'threshold' | 'range' | 'rate' | 'stale' | 'state' | 'geofence' | 'count' | 'deviation';
export type ActionKind = 'alert' | 'notify' | 'run' | 'decision' | 'command';
export const ASSET_TYPES = ['vehicle', 'machine', 'sensor', 'device', 'system'] as const;

export interface Scope {
  kind: 'asset' | 'type' | 'tag';
  group?: string;
  node?: string;
  // '*' any part, '' the asset itself, or one part
  device?: string;
  type?: string;
  tag?: string;
}

export interface Condition {
  kind: CondKind;
  signal?: string;
  op?: string;
  value?: number | string | null;
  hysteresis?: number | string | null;
  min?: number | string | null;
  max?: number | string | null;
  limit?: number | string | null;
  per?: 's' | 'min' | 'h';
  direction?: 'up' | 'down' | 'either';
  window_s?: number | string | null;
  seconds?: number | string | null;
  equals?: string | number | boolean | null;
  frame?: 'gnss' | 'site';
  x_signal?: string;
  y_signal?: string;
  polygon?: number[][];
  on?: 'enter' | 'exit';
  zone?: string;
  count?: number | string | null;
  when?: { op?: string; value?: number | string | null; equals?: string | number | boolean | null } | null;
  baseline_s?: number | string | null;
  mode?: 'ratio' | 'zscore';
  threshold?: number | string | null;
}

export interface Action {
  kind: ActionKind;
  severity?: Severity | null;
  channel?: 'in_app' | 'email' | 'slack';
  to?: string[];
  message?: string;
  agent_id?: string;
  key?: string;
  facts?: Record<string, string>;
  signal?: string;
  value?: string | number | boolean | null;
  group?: string;
  node?: string;
  device?: string;
  // run steps: wait for the answer so later steps can use {steps.N.output}
  wait?: boolean;
  wait_s?: number | string | null;
}

export interface RuleDraft {
  name: string;
  description: string;
  enabled: boolean;
  severity: Severity;
  cooldown_s: number | string;
  scope: Scope;
  condition: Condition;
  actions: Action[];
  team_id: string | null;
}

export interface ActionOutcome {
  kind: string;
  status: 'ok' | 'failed' | 'skipped' | 'pending' | 'running';
  message: string;
  ref?: Record<string, unknown> | null;
  input?: Record<string, unknown>;
  output?: unknown;
  started_at?: number;
  duration_ms?: number;
}

/** Steps before step i whose answer later steps can use, counted from 1. */
export function answeringSteps(actions: Action[], i: number): Array<{ n: number; kind: ActionKind }> {
  return actions.slice(0, i).map((a, j) => ({ n: j + 1, kind: a.kind })).filter((x) => x.kind === 'run' || x.kind === 'decision' || x.kind === 'command');
}

/** {steps.N...} that point at this step or a later one. Same check as the server. */
export function stepRefProblem(a: Action, i: number): string | null {
  const texts = [a.message, a.value === null || a.value === undefined ? '' : String(a.value), ...Object.values(a.facts || {})];
  for (const t of texts) {
    for (const m of String(t || '').matchAll(/\{\{?\s*steps\.(\d+)\./g)) {
      const n = Number(m[1]);
      if (n < 1 || n > i) return `{steps.${n}...} must name ${i ? 'an earlier step' : 'a step, and this is the first'}. Steps count from 1 in the order shown.`;
    }
  }
  return null;
}

export interface Firing {
  id: string;
  rule_id: string | null;
  rule: string;
  fired_at: string;
  cleared_at: string | null;
  status: 'firing' | 'cleared' | 'test';
  group: string;
  node: string;
  device: string;
  asset: string;
  signal: string | null;
  value: unknown;
  detail: string;
  actions: ActionOutcome[];
}

export interface Rule extends Omit<RuleDraft, 'description'> {
  id: string;
  description: string | null;
  summary: string;
  condition_words: string;
  scope_words: string;
  action_words: string[];
  fire_count: number;
  last_fired_at: string | null;
  firing_now: number;
  last_firing: Firing | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
  can_edit: boolean;
}

export interface SignalRow {
  signal: string;
  type?: string | null;
  unit?: string | null;
  value?: unknown;
  ts?: number | null;
  numeric?: boolean;
  assets: Array<{ group: string; node: string; device: string; value?: unknown; ts?: number | null; online?: boolean }>;
}

export interface PreviewAsset {
  key: string;
  group: string;
  node: string;
  device: string;
  name: string;
  firings: Array<{ t: number; value: unknown; words: string }>;
  clears: number[];
  series: Array<{ signal: string; points: Array<[number, number]> }>;
  track: Array<[number, number, number]>;
  samples: number;
  stats: Record<string, { min: number; max: number; last: number; n: number }>;
}

export interface Preview {
  from: string;
  to: string;
  hours: number;
  fired: number;
  cleared: number;
  summary: string;
  condition_words: string;
  scope_words: string;
  assets: PreviewAsset[];
  truncated: boolean;
  targets: number;
}

export interface Options {
  agents: Array<{ id: string; name: string; kind: 'agent' | 'pipeline'; status: string }>;
  decisions: Array<{ key: string; name: string }>;
  people: Array<{ id: string; name: string; email: string }>;
  teams: Array<{ id: string; name: string }>;
  can_command: boolean;
}

export const COND_INFO: Record<CondKind, { label: string; help: string }> = {
  threshold: { label: 'Above or below a limit', help: 'Fires when a reading crosses a number, like pump pressure above 300 bar.' },
  range: { label: 'Outside a normal range', help: 'Fires when a reading leaves a band, like coolant under 70 or over 105 °C.' },
  rate: { label: 'Changes too fast', help: 'Fires when a reading rises or falls faster than you allow, like a pressure spike or a sudden drop.' },
  stale: { label: 'Stops reporting', help: 'Fires when nothing arrives for a number of seconds, like a machine whose PC was unplugged.' },
  state: { label: 'Has a value', help: 'Fires when a signal is, or stops being, a value, like a mode switching to safe or a fault code appearing.' },
  geofence: { label: 'Enters or leaves a zone', help: 'Fires when a GPS or site position crosses a zone you draw, like a truck leaving the haul road.' },
  count: { label: 'Happens too often', help: 'Fires when something happens a number of times inside a window, like five overloads in ten minutes.' },
  deviation: { label: 'Drifts from normal', help: 'Fires when the last 5 minutes run 15% above the last 30 minutes, or a number of standard deviations away. Good for a pressure or a temperature trending up.' },
};

export const ACTION_INFO: Record<ActionKind, { label: string; help: string }> = {
  alert: { label: 'Raise an alert', help: 'Shows on the Alerts page and clears by itself when the condition clears.' },
  notify: { label: 'Tell people', help: 'In Abenix, by email, or on the workspace Slack channel.' },
  run: { label: 'Run an agent or pipeline', help: 'Starts it with the firing as its context: the asset, signal, value and why.' },
  decision: { label: 'Check a decision table', help: 'Evaluates a business rule with the reading as facts and keeps the result.' },
  command: { label: 'Send a command', help: 'Writes a value back to the asset through its source, with the rule as the reason.' },
};

export const SEVERITY_INFO: Record<Severity, string> = {
  info: 'Info, worth knowing',
  warning: 'Warning, look soon',
  critical: 'Critical, act now',
};

export function blankCondition(kind: CondKind, signal = ''): Condition {
  switch (kind) {
    case 'threshold': return { kind, signal, op: '>', value: '', hysteresis: '' };
    case 'range': return { kind, signal, min: '', max: '', hysteresis: '' };
    case 'rate': return { kind, signal, limit: '', per: 's', direction: 'either', window_s: 10, hysteresis: '' };
    case 'stale': return { kind, signal: '', seconds: 30 };
    case 'state': return { kind, signal, op: 'equals', equals: '' };
    case 'geofence': return { kind, frame: 'site', x_signal: '', y_signal: '', polygon: [], on: 'exit', zone: '', hysteresis: '' };
    case 'count': return { kind, signal, count: 5, window_s: 600, when: { op: '>', value: '' }, hysteresis: '' };
    case 'deviation': return { kind, signal, window_s: 300, baseline_s: 1800, mode: 'ratio', direction: 'up', threshold: 1.15, hysteresis: 0.05 };
  }
}

export function blankDraft(): RuleDraft {
  return {
    name: '',
    description: '',
    enabled: true,
    severity: 'warning',
    cooldown_s: 60,
    scope: { kind: 'asset', group: '', node: '', device: '*' },
    condition: blankCondition('threshold'),
    actions: [{ kind: 'alert', severity: null }],
    team_id: null,
  };
}

export const TEMPLATES: Array<{ id: string; label: string; help: string; build: () => Partial<RuleDraft> }> = [
  {
    id: 'limit',
    label: 'A reading goes over a limit',
    help: 'Pressure, temperature, speed or load above a number.',
    build: () => ({ condition: blankCondition('threshold'), actions: [{ kind: 'alert', severity: null }] }),
  },
  {
    id: 'silent',
    label: 'An asset stops reporting',
    help: 'Nothing heard for 30 seconds, like an unplugged PC or a dead modem.',
    build: () => ({ condition: blankCondition('stale'), severity: 'critical', actions: [{ kind: 'alert', severity: null }] }),
  },
  {
    id: 'zone',
    label: 'Something leaves or enters a zone',
    help: 'Draw the zone over GPS or site positions.',
    build: () => ({ condition: blankCondition('geofence'), actions: [{ kind: 'alert', severity: null }] }),
  },
  {
    id: 'often',
    label: 'Something happens too often',
    help: 'Overloads, fault codes or failed orders, counted in a window.',
    build: () => ({ condition: blankCondition('count'), actions: [{ kind: 'notify', channel: 'in_app', to: [], message: '' }] }),
  },
];

// client checks mirror the server, so problems show before Save

const num = (v: unknown): number | null => {
  if (v === '' || v === null || v === undefined || typeof v === 'boolean') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

export type Problems = Record<string, string>;

export function scopeProblems(s: Scope): Problems {
  const p: Problems = {};
  if (s.kind === 'asset') {
    if (!s.group) p['scope.group'] = 'Pick the group the asset is in.';
    if (!s.node) p['scope.node'] = 'Pick the asset this rule watches.';
  } else if (s.kind === 'type') {
    if (!s.type || !(ASSET_TYPES as readonly string[]).includes(s.type)) p['scope.type'] = 'Pick an asset type: vehicle, machine, sensor, device or system.';
  } else if (s.kind === 'tag') {
    if (!s.tag?.trim()) p['scope.tag'] = 'Pick a tag. Tags are set on the Assets page.';
  }
  return p;
}

export function conditionProblems(c: Condition): Problems {
  const p: Problems = {};
  const h = num(c.hysteresis) ?? 0;
  if (h < 0) p['condition.hysteresis'] = 'The margin cannot be negative.';
  if (c.kind !== 'geofence' && c.kind !== 'stale' && !c.signal?.trim()) p['condition.signal'] = 'Pick the signal to watch.';
  if (c.signal && !/^[A-Za-z0-9_.\-:/ ]{1,255}$/.test(c.signal)) p['condition.signal'] = 'Signal names are letters, digits and _ . - : / only.';
  switch (c.kind) {
    case 'threshold':
      if (num(c.value) === null) p['condition.value'] = 'Enter the number to compare with.';
      break;
    case 'range': {
      const lo = num(c.min), hi = num(c.max);
      if (lo === null) p['condition.min'] = 'Enter the lowest normal value.';
      if (hi === null) p['condition.max'] = 'Enter the highest normal value.';
      if (lo !== null && hi !== null) {
        if (lo >= hi) p['condition.max'] = 'The highest value must be above the lowest.';
        else if (lo + h > hi - h) p['condition.hysteresis'] = 'The margin is wider than half the range.';
      }
      break;
    }
    case 'rate': {
      const lim = num(c.limit);
      if (lim === null || lim <= 0) p['condition.limit'] = 'Enter how fast a change is too fast, above zero.';
      const w = num(c.window_s) ?? 10;
      if (w < 1 || w > 3600) p['condition.window_s'] = 'Measure over 1 to 3600 seconds.';
      if (lim !== null && lim > 0 && h >= lim) p['condition.hysteresis'] = 'The margin must be smaller than the limit.';
      break;
    }
    case 'stale': {
      const s = num(c.seconds);
      if (s === null || s < 1 || s > 86400) p['condition.seconds'] = 'Enter 1 to 86400 seconds.';
      break;
    }
    case 'state':
      if (c.equals === '' || c.equals === null || c.equals === undefined) p['condition.equals'] = 'Enter the value to look for.';
      break;
    case 'geofence': {
      const what = c.frame === 'gnss' ? ['longitude', 'latitude'] : ['x', 'y'];
      if (!c.x_signal) p['condition.x_signal'] = `Pick the ${what[0]} signal.`;
      if (!c.y_signal) p['condition.y_signal'] = `Pick the ${what[1]} signal.`;
      if (c.x_signal && c.x_signal === c.y_signal) p['condition.y_signal'] = `The ${what[1]} signal must differ from the ${what[0]} signal.`;
      const poly = c.polygon || [];
      if (poly.length < 3) p['condition.polygon'] = 'Draw the zone with at least 3 corners.';
      else if (poly.length > 200) p['condition.polygon'] = 'A zone can have at most 200 corners.';
      else if (c.frame === 'gnss' && poly.some(([x, y]) => x < -180 || x > 180 || y < -90 || y > 90)) {
        p['condition.polygon'] = 'Each corner needs a longitude from -180 to 180 and a latitude from -90 to 90.';
      }
      break;
    }
    case 'deviation': {
      const w = num(c.window_s) ?? 300;
      const b = num(c.baseline_s) ?? 1800;
      if (w < 10 || w > 86400) p['condition.window_s'] = 'Take the recent window over 10 to 86400 seconds.';
      if (!(w < b && b <= 7 * 86400)) p['condition.baseline_s'] = 'The baseline must be longer than the recent window, and at most 7 days.';
      const t = num(c.threshold);
      const d = c.direction || 'up';
      if (t === null || t <= 0) p['condition.threshold'] = 'Enter how far is too far, like 1.15 for 15% above or 3 for three standard deviations.';
      else if ((c.mode || 'ratio') === 'ratio') {
        if (d === 'up' && t <= 1) p['condition.threshold'] = 'Above its baseline means more than 1, like 1.15 for 15% above.';
        if (d === 'down' && t >= 1) p['condition.threshold'] = 'Below its baseline means less than 1, like 0.85 for 15% below.';
        if (d === 'either' && t <= 1) p['condition.threshold'] = 'Either way takes a factor above 1, like 1.15 for 15%.';
      } else if (h >= t) p['condition.hysteresis'] = 'The margin must be smaller than the limit.';
      break;
    }
    case 'count': {
      const n = num(c.count);
      if (n === null || n < 1 || n > 10000 || !Number.isInteger(n)) p['condition.count'] = 'Enter a whole number from 1 to 10000.';
      const w = num(c.window_s);
      if (w === null || w < 1 || w > 86400) p['condition.window_s'] = 'Enter a window of 1 to 86400 seconds.';
      if (c.when && !('equals' in c.when) && c.when.value !== '' && c.when.value !== null && c.when.value !== undefined && num(c.when.value) === null) {
        p['condition.when'] = 'Enter the reading that counts, like above 300.';
      }
      if (n !== null && h >= n) p['condition.hysteresis'] = 'The margin must be smaller than the count.';
      break;
    }
  }
  return p;
}

export function actionProblems(actions: Action[], canCommand: boolean): Problems {
  const p: Problems = {};
  if (actions.length > 8) p.actions = 'A rule can do at most 8 things.';
  actions.forEach((a, i) => {
    const k = `actions.${i}`;
    if (a.kind === 'run' && !a.agent_id) p[`${k}.agent_id`] = 'Pick the agent or pipeline to run.';
    const ref = stepRefProblem(a, i);
    if (ref) p[`${k}.${a.kind === 'command' ? 'value' : a.kind === 'decision' ? 'facts' : 'message'}`] = ref;
    if (a.kind === 'run' && a.wait_s !== undefined && a.wait_s !== null && a.wait_s !== '') {
      const w = Number(a.wait_s);
      if (!Number.isFinite(w) || w < 5 || w > 3600) p[`${k}.wait_s`] = 'Wait from 5 seconds to an hour.';
    }
    if (a.kind === 'decision' && !a.key) p[`${k}.key`] = 'Pick the decision table to evaluate.';
    if (a.kind === 'command') {
      if (!canCommand) p[`${k}.kind`] = 'Sending commands needs Send machine commands. An admin can add you to Machine operators under Admin, Permissions.';
      if (!a.signal?.trim()) p[`${k}.signal`] = 'Pick the signal to write, like Safety/Hold.';
      if (a.value === '' || a.value === null || a.value === undefined) p[`${k}.value`] = 'Enter the value to send.';
    }
  });
  return p;
}

export function draftProblems(d: RuleDraft, canCommand: boolean, otherNames: string[] = []): Problems {
  const p: Problems = { ...scopeProblems(d.scope), ...conditionProblems(d.condition), ...actionProblems(d.actions, canCommand) };
  const name = d.name.trim();
  if (!name) p.name = 'Give the rule a name people will recognise.';
  else if (name.length > 160) p.name = 'Keep the name under 160 characters.';
  else if (otherNames.some((n) => n.toLowerCase() === name.toLowerCase())) p.name = 'Another rule already has this name.';
  if (d.description.length > 1000) p.description = 'Keep the description under 1000 characters.';
  const cd = num(d.cooldown_s);
  if (cd === null || cd < 0 || cd > 86400) p.cooldown_s = 'Wait 0 to 86400 seconds between firings.';
  return p;
}

// what preview and save send: numbers as numbers, empty optional fields dropped

function n(v: unknown): number | null {
  return num(v);
}

export function conditionPayload(c: Condition): Record<string, unknown> {
  const out: Record<string, unknown> = { kind: c.kind };
  const keep = (k: keyof Condition, asNum = false) => {
    const v = c[k];
    if (v === undefined || v === '') return;
    out[k] = asNum ? n(v) : v;
  };
  if (c.kind !== 'geofence') keep('signal');
  if (c.kind === 'threshold') { keep('op'); keep('value', true); keep('hysteresis', true); }
  if (c.kind === 'range') { keep('min', true); keep('max', true); keep('hysteresis', true); }
  if (c.kind === 'rate') { keep('limit', true); keep('per'); keep('direction'); keep('window_s', true); keep('hysteresis', true); }
  if (c.kind === 'stale') keep('seconds', true);
  if (c.kind === 'deviation') {
    keep('window_s', true); keep('baseline_s', true); keep('mode'); keep('direction'); keep('threshold', true); keep('hysteresis', true);
  }
  if (c.kind === 'state') { keep('op'); out.equals = typedValue(c.equals); }
  if (c.kind === 'geofence') { keep('frame'); keep('x_signal'); keep('y_signal'); out.polygon = c.polygon || []; keep('on'); keep('zone'); keep('hysteresis', true); }
  if (c.kind === 'count') {
    keep('count', true); keep('window_s', true); keep('hysteresis', true);
    const w = c.when;
    if (w && 'equals' in w && w.equals !== '' && w.equals !== undefined) out.when = { equals: typedValue(w.equals) };
    else if (w && w.value !== '' && w.value !== null && w.value !== undefined) out.when = { op: w.op || '>', value: n(w.value) };
    else out.when = null;
  }
  return out;
}

// "true" and "12" typed in a text box mean the bool and the number
export function typedValue(v: unknown): unknown {
  if (typeof v !== 'string') return v;
  const s = v.trim();
  if (s === 'true' || s === 'false') return s === 'true';
  if (s !== '' && Number.isFinite(Number(s))) return Number(s);
  return s;
}

export function draftPayload(d: RuleDraft): Record<string, unknown> {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    enabled: d.enabled,
    severity: d.severity,
    cooldown_s: n(d.cooldown_s) ?? 60,
    scope: d.scope.kind === 'asset'
      ? { kind: 'asset', group: d.scope.group, node: d.scope.node, device: d.scope.device ?? '*' }
      : d.scope.kind === 'type'
        ? { kind: 'type', type: d.scope.type, group: d.scope.group || '' }
        : { kind: 'tag', tag: (d.scope.tag || '').trim().toLowerCase(), group: d.scope.group || '' },
    condition: conditionPayload(d.condition),
    actions: d.actions.map((a) => {
      if (a.kind === 'command') return { ...a, value: typedValue(a.value) };
      return a;
    }),
    team_id: d.team_id || null,
  };
}

export function draftFromRule(r: Rule): RuleDraft {
  const c = { ...r.condition } as Condition;
  if (c.kind === 'count' && !c.when) c.when = { op: '>', value: '' };
  return {
    name: r.name,
    description: r.description || '',
    enabled: r.enabled,
    severity: r.severity,
    cooldown_s: r.cooldown_s,
    scope: { device: '*', ...r.scope },
    condition: c,
    actions: (r.actions || []).map((a) => ({ ...a })),
    team_id: r.team_id,
  };
}

// plain words, the same sentences the server builds

export function fmt(v: unknown): string {
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v);
    return String(Math.round(v * 1000) / 1000);
  }
  if (v === null || v === undefined || v === '') return '–';
  return String(v);
}

const PER: Record<string, string> = { s: 'second', min: 'minute', h: 'hour' };

export function conditionWords(c: Condition): string {
  const sig = c.signal || 'the signal';
  const h = num(c.hysteresis) ?? 0;
  switch (c.kind) {
    case 'threshold': {
      const op = c.op || '>';
      const word = ({ '>': 'goes above', '>=': 'reaches', '<': 'drops below', '<=': 'drops to' } as Record<string, string>)[op];
      const v = num(c.value);
      let s = `${sig} ${word} ${fmt(c.value)}`;
      if (h && v !== null) s += ` (clears ${op.startsWith('>') ? 'at or below' : 'at or above'} ${fmt(op.startsWith('>') ? v - h : v + h)})`;
      return s;
    }
    case 'range': return `${sig} leaves the range ${fmt(c.min)} to ${fmt(c.max)}${h ? ` (clears ${fmt(h)} inside it)` : ''}`;
    case 'rate': {
      const d = ({ up: 'rises', down: 'falls', either: 'changes' } as Record<string, string>)[c.direction || 'either'];
      return `${sig} ${d} faster than ${fmt(c.limit)} a ${PER[c.per || 's']} over ${fmt(c.window_s ?? 10)} s`;
    }
    case 'stale': return `no ${c.signal || 'data'} arrives for ${fmt(c.seconds)} s`;
    case 'state': return `${sig} ${c.op === 'not_equals' ? 'is not' : 'is'} ${fmt(c.equals)}`;
    case 'geofence': return `the ${c.frame === 'gnss' ? 'GPS position' : 'site position'} ${c.on === 'enter' ? 'enters' : 'leaves'} ${c.zone || 'the drawn zone'}`;
    case 'deviation': {
      const win = fmt(Math.round(((num(c.window_s) ?? 300) / 60) * 100) / 100);
      const base = fmt(Math.round(((num(c.baseline_s) ?? 1800) / 60) * 100) / 100);
      const t = num(c.threshold) ?? 0;
      const d = c.direction || 'up';
      let how: string;
      if ((c.mode || 'ratio') === 'ratio') {
        const pct = fmt(Math.round(Math.abs(t - 1) * 1000) / 10);
        how = d === 'up' ? `${pct}% above` : d === 'down' ? `${pct}% below` : `${pct}% either way from`;
      } else {
        const sd = `more than ${fmt(t)} standard deviations`;
        how = d === 'up' ? `${sd} above` : d === 'down' ? `${sd} below` : `${sd} either way from`;
      }
      return `the last ${win} min of ${sig} run ${how} the last ${base} min`;
    }
    case 'count': {
      let what = sig;
      const w = c.when;
      if (w && 'equals' in w && w.equals !== '' && w.equals !== undefined) what += ` is ${fmt(w.equals)}`;
      else if (w && w.value !== '' && w.value !== null && w.value !== undefined) what += ` ${w.op || '>'} ${fmt(w.value)}`;
      return `${what} happens ${fmt(c.count)} times within ${fmt(c.window_s)} s`;
    }
  }
}

export function scopeWords(s: Scope, names: Record<string, string> = {}): string {
  if (s.kind === 'asset') {
    const base = names[`${s.group}/${s.node}/`] || s.node || 'an asset';
    if (s.device === '*' || s.device === undefined) return `${base} or any of its parts`;
    if (s.device) return `${base} part ${s.device}`;
    return base;
  }
  const g = s.group ? ` in ${s.group}` : '';
  if (s.kind === 'type') return `any ${s.type || 'asset type'}${g}`;
  return `assets tagged ${s.tag || '?'}${g}`;
}

export function actionWords(a: Action, labels: Record<string, string> = {}): string {
  switch (a.kind) {
    case 'alert': return 'raise an alert';
    case 'notify':
      if (a.channel === 'slack') return 'post to the workspace Slack channel';
      return `tell ${a.to?.length ? `${a.to.length} ${a.to.length === 1 ? 'person' : 'people'}` : 'the workspace admins'} ${a.channel === 'email' ? 'by email' : 'in Abenix'}`;
    case 'run': return `run ${labels[a.agent_id || ''] || 'an agent'}`;
    case 'decision': return `evaluate the decision ${a.key || '?'}`;
    case 'command': return `set ${a.signal || '?'} to ${fmt(typedValue(a.value))}`;
  }
}

export function ruleSentence(d: RuleDraft, names: Record<string, string> = {}, labels: Record<string, string> = {}): string {
  const acts = d.actions.map((a) => actionWords(a, labels));
  const then = acts.length === 0 ? 'record it' : acts.length === 1 ? acts[0] : `${acts.slice(0, -1).join(', ')} and ${acts[acts.length - 1]}`;
  return `When ${conditionWords(d.condition)} on ${scopeWords(d.scope, names)}, ${then}.`;
}

export function ago(iso: string | number | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const t = typeof iso === 'number' ? iso : Date.parse(iso);
  if (!Number.isFinite(t)) return 'never';
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export function clockTime(iso: string | number): string {
  const d = new Date(iso);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function dayTime(iso: string | number): string {
  const d = new Date(iso);
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// the server says condition.value or actions.0.agent_id, the form shows it under that field
export function fieldErrors(res: { errorDetail?: { details?: Record<string, unknown> | null } | null } | null | undefined): Problems {
  const f = res?.errorDetail?.details?.fields;
  if (!f || typeof f !== 'object') return {};
  const out: Problems = {};
  for (const [k, v] of Object.entries(f as Record<string, unknown>)) if (typeof v === 'string') out[k] = v;
  return out;
}

// the preview runs once scope and condition make sense, without a name or steps
export function previewReady(d: RuleDraft): boolean {
  return Object.keys(scopeProblems(d.scope)).length === 0 && Object.keys(conditionProblems(d.condition)).length === 0;
}

export function previewBody(d: RuleDraft, hours: number): Record<string, unknown> {
  const p = draftPayload(d);
  return { scope: p.scope, condition: p.condition, cooldown_s: p.cooldown_s, hours };
}

export function sameDraft(a: RuleDraft, b: RuleDraft): boolean {
  return JSON.stringify(draftPayload(a)) === JSON.stringify(draftPayload(b));
}

// polygon helpers for the zone editor

export interface Bounds { minX: number; maxX: number; minY: number; maxY: number }

export function boundsOf(points: number[][], pad = 0.1): Bounds | null {
  if (!points.length) return null;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const [x, y] of points) {
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  }
  if (!Number.isFinite(minX)) return null;
  let w = maxX - minX, h = maxY - minY;
  if (w === 0) w = Math.abs(minX) * 0.001 || 10;
  if (h === 0) h = Math.abs(minY) * 0.001 || 10;
  // square-ish so a circle drawn looks like one
  const side = Math.max(w, h);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const half = (side * (1 + pad * 2)) / 2;
  return { minX: cx - half, maxX: cx + half, minY: cy - half, maxY: cy + half };
}

export function pointInPolygon(x: number, y: number, poly: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-300) + xi) inside = !inside;
  }
  return inside;
}

export function roundCoord(v: number, gnss: boolean): number {
  const k = gnss ? 1e6 : 100;
  return Math.round(v * k) / k;
}

// the reading behind a firing in words: a deviation as a percent from normal, a zone crossing as where
export function firingValueText(f: Pick<Firing, 'value' | 'detail' | 'signal'>): string | null {
  const v = f.value;
  if (v === null || v === undefined) return null;
  if (Array.isArray(v) && v.length === 2 && v.every((x) => typeof x === 'number')) {
    const verb = /entered/i.test(f.detail || '') ? 'entered the zone at' : 'left the zone at';
    return `${verb} ${fmt(v[0])}, ${fmt(v[1])}`;
  }
  const dev = /(\d+(?:\.\d+)?)\s?% (above|below)/i.exec(f.detail || '');
  if (dev) return `${dev[1]}% ${dev[2].toLowerCase()} normal`;
  return `= ${Array.isArray(v) ? v.map((x) => fmt(x)).join(', ') : fmt(v)}`;
}

export function speed(ms: number): string {
  if (ms < 1) return 'under a millisecond';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

// how quickly the rules act, in words, the slowest of nearly every reading
export function rulesSpeedText(lagMs: number | null): string {
  if (lagMs === null) return '';
  return lagMs < 1 ? 'Rules act on new readings at once.' : `Rules act on new readings within ${speed(lagMs)}.`;
}
