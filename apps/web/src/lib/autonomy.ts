import { apiFetch, type ApiErrorDetail } from '@/lib/api-client';

// Shapes follow the Earned Autonomy build contract. Every field the API may leave out is optional.

export type Level = 0 | 1 | 2 | 3 | 4;

export interface LevelMeta {
  level: Level;
  key: 'off' | 'watching' | 'asks_first' | 'within_limits' | 'acts_reports';
  label: string;
  help: string;
  short: string;
  // tailwind classes
  text: string;
  bg: string;
  border: string;
  fill: string;
}

export const LEVELS: readonly LevelMeta[] = [
  {
    level: 0, key: 'off', label: 'Off', short: 'Off',
    help: 'The agent cannot take this action',
    text: 'text-slate-300', bg: 'bg-slate-500/15', border: 'border-slate-500/40', fill: 'bg-slate-400',
  },
  {
    level: 1, key: 'watching', label: 'Watching', short: 'Watching',
    help: 'The agent says what it would do. Nothing runs',
    text: 'text-sky-300', bg: 'bg-sky-500/15', border: 'border-sky-500/40', fill: 'bg-sky-400',
  },
  {
    level: 2, key: 'asks_first', label: 'Asks first', short: 'Asks first',
    help: 'A person approves, edits or rejects, then it runs',
    text: 'text-amber-300', bg: 'bg-amber-500/15', border: 'border-amber-500/40', fill: 'bg-amber-400',
  },
  {
    level: 3, key: 'within_limits', label: 'Acts within limits', short: 'Within limits',
    help: 'Runs alone inside the limits with a confident prediction, otherwise asks first',
    text: 'text-cyan-300', bg: 'bg-cyan-500/15', border: 'border-cyan-500/40', fill: 'bg-cyan-400',
  },
  {
    level: 4, key: 'acts_reports', label: 'Acts and reports', short: 'Acts and reports',
    help: 'Runs and reports after. Limits and kill switches still apply',
    text: 'text-emerald-300', bg: 'bg-emerald-500/15', border: 'border-emerald-500/40', fill: 'bg-emerald-400',
  },
] as const;

export function levelMeta(level: number | null | undefined): LevelMeta {
  const n = typeof level === 'number' && Number.isFinite(level) ? Math.round(level) : 0;
  return LEVELS[Math.min(4, Math.max(0, n))];
}

export function levelLabel(level: number | null | undefined): string {
  if (level === null || level === undefined) return 'Not enrolled';
  return levelMeta(level).label;
}

// ---- JSON shapes

export interface Prediction {
  metric?: string;
  value?: number | string | null;
  low?: number | null;
  high?: number | null;
  horizon_s?: number | null;
  source?: 'agent_stated' | 'decision' | 'ml_model' | 'none' | string;
  source_ref?: string | null;
  note?: string | null;
}

export interface WorldModel {
  kind: 'agent_stated' | 'decision' | 'ml_model' | 'none' | string;
  ref?: string | null;
  metric?: string | null;
  inputs?: Record<string, string>;
  timeout_s?: number | null;
}

export interface OutcomeProbe {
  kind: 'tool' | 'manual' | 'api' | 'none' | string;
  after_s?: number | null;
  tool?: string | null;
  arguments?: Record<string, unknown> | null;
  path?: string | null;
  metric?: string | null;
}

export interface Outcome {
  metric?: string;
  value?: number | string | null;
  source?: 'tool' | 'manual' | 'api' | string;
  observed_at?: string | null;
  by?: string | null;
}

export interface Score {
  within_band?: boolean | null;
  band_ok?: boolean;
  agreement?: number | null;
  harm?: boolean;
}

export interface LimitsResult {
  ok?: boolean;
  decision_key?: string | null;
  reasons?: string[];
}

export interface Effect {
  kind: string;
  label: string;
  target_param?: string | null;
  magnitude_param?: string | null;
  reversible?: boolean;
}

export interface Scope {
  param?: string;
  equals?: unknown;
  [k: string]: unknown;
}

export interface ActionCardData {
  action_id?: string;
  action_type?: { key?: string; label?: string; reversible?: boolean } | null;
  agent?: { id?: string | null; name?: string | null } | null;
  level?: number | null;
  level_label?: string | null;
  target?: string | null;
  arguments?: Record<string, unknown> | null;
  intent?: string | null;
  prediction?: Prediction | null;
  limits?: LimitsResult | null;
  fallback_reason?: string | null;
  record?: { held?: number; scored?: number; agreement_pct?: number | null; text?: string } | null;
  editable_arguments?: boolean;
  situation?: string | null;
  grant_id?: string | null;
}

export interface Requirement {
  key: string;
  label: string;
  current?: number | string | null;
  needed?: number | string | null;
  met: boolean;
  fix?: { label: string; href: string } | null;
}

export interface NextStep {
  next_level?: number | null;
  requirements?: Requirement[];
  ready?: boolean;
  blocked_by_ceiling?: boolean;
  demote_to?: number | null;
  demote_reason?: string | null;
}

export interface GrantStats {
  scored?: number;
  held?: number;
  accuracy_pct?: number | null;
  accuracy_lb_pct?: number | null;
  reviews?: number;
  agreement_pct?: number | null;
  executed?: number;
  rejected?: number;
  unknown?: number;
  harm_30d?: number;
}

export interface ActionTypeRef {
  id: string;
  key: string;
  label: string;
  is_sample?: boolean;
}

export interface ActionType extends ActionTypeRef {
  description?: string | null;
  tool_name?: string;
  match?: { param?: string; glob?: string } | null;
  effect?: Effect | null;
  world_model?: WorldModel | null;
  outcome_probe?: OutcomeProbe | null;
  limits_decision_key?: string | null;
  max_band_width?: number | null;
  reversible?: boolean;
  ceiling?: number | null;
  policy?: Record<string, unknown> | null;
  effective_policy?: Record<string, unknown> | null;
}

export interface GrantRow {
  id: string;
  agent: { id: string; name: string };
  action_type: ActionTypeRef;
  scope?: Scope | null;
  level: number;
  level_label?: string;
  ceiling?: number | null;
  state?: 'active' | 'paused' | string;
  level_since?: string | null;
  stats?: GrantStats;
  next?: NextStep | null;
  spark?: Array<number | null>;
  attention?: string | null;
  // set when the hard limits cannot be checked, every action is blocked until fixed
  limits_problem?: string | null;
  agent_config_hash?: string | null;
}

export interface AutonomyChange {
  id?: string;
  from_level: number;
  to_level: number;
  actor_type?: 'user' | 'system' | string;
  actor_id?: string | null;
  actor_name?: string | null;
  reason?: string | null;
  evidence?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface ChartPoint {
  id: string;
  created_at?: string | null;
  value?: number | null;
  low?: number | null;
  high?: number | null;
  actual?: number | null;
  within_band?: boolean | null;
  revision_marker?: boolean;
  world_model_marker?: boolean;
}

export interface GrantDetail extends Omit<GrantRow, 'action_type'> {
  action_type: ActionType;
  // the thresholds in force, tier defaults merged with the action type's own
  policy?: Record<string, unknown> | null;
  changes?: AutonomyChange[];
  chart?: ChartPoint[];
}

export type ActionStatus =
  | 'recorded' | 'watching' | 'pending' | 'approved' | 'edited' | 'rejected'
  | 'executed' | 'failed' | 'blocked' | 'expired';

export type ActionMode = 'unmanaged' | 'watching' | 'proposed' | 'auto' | 'reported' | 'external';

export interface ActionRow {
  id: string;
  created_at?: string | null;
  agent?: { id?: string | null; name?: string | null } | null;
  action_type?: { key: string; label: string } | null;
  tool_name?: string;
  mode?: ActionMode | string;
  status?: ActionStatus | string;
  level_at_time?: number | null;
  level_label?: string | null;
  target?: string | null;
  arguments?: Record<string, unknown> | null;
  intent?: string | null;
  prediction?: Prediction | null;
  outcome?: Outcome | null;
  outcome_status?: 'none' | 'pending' | 'observed' | 'unknown' | 'manual' | string;
  outcome_due_at?: string | null;
  score?: Score | null;
  harm?: boolean;
  harm_note?: string | null;
  reviewer_answer?: 'agree' | 'different' | 'unsure' | null;
  reviewer_alternative?: string | null;
  decided_by_name?: string | null;
  decision_note?: string | null;
  execution_id?: string | null;
  approval_id?: string | null;
  result_preview?: string | null;
  executed_at?: string | null;
  card?: ActionCardData | null;
  situation?: string | null;
}

export interface UnmanagedRow {
  agent_id: string;
  agent_name: string;
  tool_name: string;
  count_7d: number;
  suggested_action_type?: Partial<ActionType> | null;
}

export interface Overview {
  counts: {
    actions_7d: number;
    auto_7d: number;
    harm_7d: number;
    pending_reviews: number;
    pending_approvals: number;
  };
  grants: GrantRow[];
  ready_to_promote: GrantRow[];
  recently_demoted: Array<{ grant: GrantRow; change: AutonomyChange }>;
  unmanaged: UnmanagedRow[];
}

export interface EnrolPrefill {
  label?: string;
  world_model?: WorldModel | null;
  outcome_probe?: OutcomeProbe | null;
  limits_decision_key?: string | null;
  max_band_width?: number | null;
  match_param?: string;
}

export interface EnrolTool {
  tool_name: string;
  effect?: Effect | null;
  risk_tier?: string | null;
  existing_action_type?: Partial<ActionType> | null;
  existing_action_types?: ActionType[];
  grant?: GrantRow | null;
  grants?: GrantRow[];
  prefill?: EnrolPrefill;
}

export interface EnrolOptions {
  agent: { id: string; name: string; [k: string]: unknown };
  tools: EnrolTool[];
}

export interface EnrolBody {
  agent_id: string;
  tool_name: string;
  action_type: {
    key?: string;
    label: string;
    world_model: WorldModel;
    outcome_probe: OutcomeProbe;
    limits_decision_key: string | null;
    max_band_width: number | null;
    match?: Record<string, unknown>;
    policy?: Record<string, unknown>;
  };
  scope?: Scope;
}

export interface TestResult {
  ok: boolean;
  result?: unknown;
  message?: string;
}

// ---- client

export interface Res<T> {
  data: T | null;
  error: string | null;
  code?: string;
  details?: Record<string, unknown>;
  status?: number;
}

function wrap<T>(r: { data: T | null; error: string | null; errorDetail?: ApiErrorDetail | null }): Res<T> {
  return {
    data: r.data,
    error: r.error,
    code: r.errorDetail?.error_code,
    details: r.errorDetail?.details,
    status: r.errorDetail?.code,
  };
}

const BASE = '/api/autonomy';

async function get<T>(path: string): Promise<Res<T>> {
  return wrap(await apiFetch<T>(`${BASE}${path}`, { silent: true }));
}

async function send<T>(method: string, path: string, body?: unknown): Promise<Res<T>> {
  return wrap(
    await apiFetch<T>(`${BASE}${path}`, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
      throwOnError: false,
    }),
  );
}

const enc = encodeURIComponent;

export const autonomyApi = {
  overview: () => get<Overview>('/overview'),
  grant: (id: string) => get<GrantDetail>(`/grants/${enc(id)}`),
  actions: (id: string, opts: { status?: string; limit?: number; before?: string } = {}) => {
    const q = new URLSearchParams();
    if (opts.status) q.set('status', opts.status);
    q.set('limit', String(opts.limit ?? 20));
    if (opts.before) q.set('before', opts.before);
    return get<{ items: ActionRow[]; next_before?: string | null }>(`/grants/${enc(id)}/actions?${q}`);
  },
  promote: (id: string) => send<{ id: string; [k: string]: unknown }>('POST', `/grants/${enc(id)}/promote`),
  // same signoff the Approvals page sends, recorded as self-approved
  approveSelf: async (approvalId: string) =>
    wrap<unknown>(
      await apiFetch<unknown>(`/api/approvals/${enc(approvalId)}/signoff`, {
        method: 'POST',
        body: JSON.stringify({ decision: 'approve', reason: 'Self-approved from the autonomy page' }),
        throwOnError: false,
      }),
    ),
  demote: (id: string, to_level: number, reason: string) =>
    send<GrantRow>('POST', `/grants/${enc(id)}/demote`, { to_level, reason }),
  patchGrant: (id: string, body: { state?: string; scope?: Scope | null; ceiling?: number }) =>
    send<GrantRow>('PATCH', `/grants/${enc(id)}`, body),
  deleteGrant: (id: string) => send<unknown>('DELETE', `/grants/${enc(id)}`),
  patchActionType: (id: string, body: { policy?: Policy | null; limits_decision_key?: string | null }) =>
    send<ActionType>('PATCH', `/action-types/${enc(id)}`, body),
  testActionType: (id: string, part: 'world_model' | 'outcome_probe' | 'limits', action_id?: string) =>
    send<TestResult>('POST', `/action-types/${enc(id)}/test`, action_id ? { part, action_id } : { part }),
  enrolOptions: (agentId: string) => get<EnrolOptions>(`/enrol/options?agent_id=${enc(agentId)}`),
  enrol: (body: EnrolBody) => send<GrantRow>('POST', '/enrol', body),
  sample: () => send<{ grant: GrantRow; agent_id: string }>('POST', '/sample'),
  sampleRun: (count: number) => send<unknown>('POST', '/sample/run', { count }),
  reviews: (limit = 50) => get<ActionRow[] | { items: ActionRow[]; total?: number }>(`/reviews?limit=${limit}`),
  review: (id: string, answer: 'agree' | 'different' | 'unsure', alternative?: string) =>
    send<ActionRow>('POST', `/actions/${enc(id)}/review`, alternative ? { answer, alternative } : { answer }),
  outcome: (id: string, value: number | string, note?: string) =>
    send<ActionRow>('POST', `/actions/${enc(id)}/outcome`, note ? { value, note } : { value }),
  harm: (id: string, note: string) => send<ActionRow>('POST', `/actions/${enc(id)}/harm`, { note }),
  action: (id: string) => get<ActionRow>(`/actions/${enc(id)}`),
};

// /sample/run may return a list or {execution_ids}
export function executionIdsOf(data: unknown): string[] {
  if (Array.isArray(data)) return data.map((x) => (typeof x === 'string' ? x : (x as { id?: string })?.id)).filter(Boolean) as string[];
  if (data && typeof data === 'object') {
    const d = data as Record<string, unknown>;
    const ids = d.execution_ids ?? d.executions ?? d.ids;
    if (Array.isArray(ids)) return executionIdsOf(ids);
  }
  return [];
}

// same signoff the Approvals page sends
export async function signoffApproval(
  id: string,
  decision: 'approve' | 'deny' | 'return',
  reason?: string,
  editedArguments?: Record<string, unknown>,
): Promise<Res<unknown>> {
  return wrap<unknown>(
    await apiFetch<unknown>(`/api/approvals/${enc(id)}/signoff`, {
      method: 'POST',
      body: JSON.stringify(editedArguments ? { decision, reason, edited_arguments: editedArguments } : { decision, reason }),
      throwOnError: false,
    }),
  );
}

export function signoffErrorText(r: Res<unknown>): string | null {
  if (!r.error) return null;
  if (r.status === 403) return 'You need the approvals permission for this.';
  return r.error;
}

// ---- sample run summary

export interface RunResult {
  id: string;
  status: string;
  output?: string | null;
}

export interface RunSummary {
  total: number;
  finished: number;
  timedOut: boolean;
  failed: string[];
  newActions: number;
  quiet: number;
  quietSaid: string | null;
  reviewStatus: 'watching' | 'pending' | null;
  reviewCount: number;
}

const FAILED = ['failed', 'cancelled', 'canceled', 'error'];
export const RUN_DONE = ['completed', ...FAILED];

function firstSentence(text: string | null | undefined, max = 140): string | null {
  const t = (text || '').replace(/\s+/g, ' ').trim();
  if (!t) return null;
  const m = t.match(/^.*?[.!?](\s|$)/);
  const s = (m ? m[0] : t).trim();
  return s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s;
}

export function reviewStatusFor(level: number): 'watching' | 'pending' | null {
  return level === 1 ? 'watching' : level === 2 ? 'pending' : null;
}

export function summarizeRuns(opts: {
  runIds: string[];
  results: Record<string, RunResult>;
  beforeIds: string[];
  after: ActionRow[];
  level: number;
  timedOut: boolean;
}): RunSummary {
  const ids = opts.runIds.filter((id) => id !== 'pending');
  const before = new Set(opts.beforeIds);
  const fresh = opts.after.filter((a) => !before.has(a.id));
  const done = ids.map((id) => opts.results[id]).filter(Boolean) as RunResult[];
  const failed = done.filter((r) => FAILED.includes(r.status)).map((r) => r.id);
  const completed = done.filter((r) => r.status === 'completed');

  // runs that left no action behind
  const traced = new Set(fresh.map((a) => a.execution_id).filter(Boolean) as string[]);
  const quietRuns = traced.size
    ? completed.filter((r) => !traced.has(r.id))
    : fresh.length ? [] : completed;
  const quiet = traced.size || !fresh.length ? quietRuns.length : Math.max(0, completed.length - fresh.length);

  const reviewStatus = reviewStatusFor(opts.level);
  const reviewCount = reviewStatus
    ? fresh.filter((a) => a.status === reviewStatus && !(reviewStatus === 'watching' && a.reviewer_answer)).length
    : 0;

  return {
    total: ids.length,
    finished: done.length,
    timedOut: opts.timedOut,
    failed,
    newActions: fresh.length,
    quiet,
    quietSaid: quietRuns.map((r) => firstSentence(r.output)).find(Boolean) || null,
    reviewStatus,
    reviewCount,
  };
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function runSummaryText(s: RunSummary): string {
  const out: string[] = [];
  if (s.timedOut) {
    out.push(s.total ? `Stopped watching after 4 minutes. ${s.finished} of ${plural(s.total, 'run')} finished.` : 'Stopped watching after 4 minutes.');
  } else {
    out.push(`${plural(s.finished, 'run')} finished.`);
  }
  if (s.newActions > 0) {
    out.push(`${plural(s.newActions, 'new action')} below.`);
    if (s.quiet > 0) out.push(`${plural(s.quiet, 'run')} changed nothing${s.quiet === 1 && s.quietSaid ? `: "${s.quietSaid}"` : '.'}`);
  } else {
    out.push('The agent found nothing to change.');
    if (s.quietSaid) out.push(`It said: "${s.quietSaid}"`);
  }
  return out.join(' ');
}

export function reviewItemsOf(data: unknown): { items: ActionRow[]; total: number } {
  if (Array.isArray(data)) return { items: data as ActionRow[], total: data.length };
  if (data && typeof data === 'object') {
    const d = data as { items?: ActionRow[]; total?: number };
    const items = Array.isArray(d.items) ? d.items : [];
    return { items, total: typeof d.total === 'number' ? d.total : items.length };
  }
  return { items: [], total: 0 };
}

// ---- plain words

export const STATUS_META: Record<string, { label: string; tone: string }> = {
  recorded: { label: 'Recorded', tone: 'bg-slate-500/15 text-slate-300 border-slate-500/40' },
  watching: { label: 'Watched, not run', tone: 'bg-sky-500/15 text-sky-300 border-sky-500/40' },
  pending: { label: 'Waiting for approval', tone: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
  approved: { label: 'Approved', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  edited: { label: 'Approved with edits', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  rejected: { label: 'Rejected', tone: 'bg-rose-500/15 text-rose-300 border-rose-500/40' },
  executed: { label: 'Done', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  failed: { label: 'Failed', tone: 'bg-rose-500/15 text-rose-300 border-rose-500/40' },
  blocked: { label: 'Blocked', tone: 'bg-rose-500/15 text-rose-300 border-rose-500/40' },
  expired: { label: 'Expired', tone: 'bg-slate-500/15 text-slate-400 border-slate-500/40' },
};

export function statusMeta(status: string | null | undefined) {
  return STATUS_META[status || ''] || { label: status || 'Unknown', tone: 'bg-slate-500/15 text-slate-300 border-slate-500/40' };
}

export const MODE_LABEL: Record<string, string> = {
  unmanaged: 'Not managed',
  watching: 'Watching',
  proposed: 'Asked first',
  auto: 'Ran on its own',
  reported: 'Ran and reported',
  external: 'From an app',
};

export const STATUS_FILTERS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All' },
  { value: 'watching', label: 'Watched' },
  { value: 'pending', label: 'Waiting' },
  { value: 'executed', label: 'Done' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'failed', label: 'Failed' },
];

export function fmtNum(v: unknown): string {
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v);
    return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  }
  if (v === null || v === undefined || v === '') return '';
  return String(v);
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '';
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} minute${m === 1 ? '' : 's'}`;
  const h = Math.round(m / 60);
  if (h < 48) return `${h} hour${h === 1 ? '' : 's'}`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? '' : 's'}`;
}

export function predictionText(p: Prediction | null | undefined): string {
  if (!p || p.value === null || p.value === undefined || p.source === 'none') return 'No prediction';
  const metric = p.metric ? `${p.metric.replace(/_/g, ' ')} ` : '';
  const band = typeof p.low === 'number' && typeof p.high === 'number' ? ` (between ${fmtNum(p.low)} and ${fmtNum(p.high)})` : '';
  const when = p.horizon_s ? ` in ${fmtDuration(p.horizon_s)}` : '';
  return `${metric}${fmtNum(p.value)}${band}${when}`;
}

export const WORLD_MODEL_KINDS: Array<{ value: string; label: string; help: string }> = [
  { value: 'agent_stated', label: 'The agent says what it expects', help: 'The agent passes its own prediction with each call.' },
  { value: 'decision', label: 'A decision model predicts it', help: 'A rule set from Decisions works out the expected result.' },
  { value: 'ml_model', label: 'An ML model predicts it', help: 'A deployed model from ML Models predicts the result.' },
  { value: 'none', label: 'No prediction', help: 'Nothing is predicted. This action cannot go past Asks first.' },
];

export const PROBE_KINDS: Array<{ value: string; label: string; help: string }> = [
  { value: 'tool', label: 'Read it with a tool', help: 'A tool reads the result after a delay.' },
  { value: 'manual', label: 'A person enters it', help: 'Someone types the result on the action card.' },
  { value: 'api', label: 'An app reports it', help: 'An app sends the result through the SDK.' },
];

export function worldModelText(wm: WorldModel | null | undefined): string {
  if (!wm || wm.kind === 'none') return 'Nothing is predicted for this action.';
  const metric = wm.metric ? ` ${wm.metric.replace(/_/g, ' ')}` : ' the result';
  if (wm.kind === 'agent_stated') return `The agent states what it expects${metric} to be, with a low and high band.`;
  if (wm.kind === 'decision') return `The decision model ${wm.ref || '(not set)'} predicts${metric}.`;
  if (wm.kind === 'ml_model') return `The ML model ${wm.ref || '(not set)'} predicts${metric}.`;
  return `Predicted by ${wm.kind}${wm.ref ? ` ${wm.ref}` : ''}.`;
}

export function probeText(p: OutcomeProbe | null | undefined): string {
  if (!p || p.kind === 'none') return 'Results are not checked for this action.';
  const after = p.after_s ? ` ${fmtDuration(p.after_s)} after the action` : '';
  const metric = p.metric ? p.metric.replace(/_/g, ' ') : 'the result';
  if (p.kind === 'tool') return `We read ${metric} with the ${p.tool || '(not set)'} tool${after}.`;
  if (p.kind === 'manual') return `A person enters ${metric} on the action card${after}.`;
  if (p.kind === 'api') return `An app reports ${metric} through the SDK${after}.`;
  return `Checked by ${p.kind}${after}.`;
}

export function scopeText(scope: Scope | null | undefined): string {
  if (!scope || !scope.param) return 'Everywhere';
  if ('equals' in scope) return `Only when ${String(scope.param).replace(/_/g, ' ')} is ${fmtNum(scope.equals)}`;
  return `Only for ${scope.param}`;
}

// lower is better for these
const INVERTED = /(unknown|reject|max_)/;

export function requirementProgress(r: Requirement): number {
  const cur = typeof r.current === 'number' ? r.current : Number(r.current);
  const need = typeof r.needed === 'number' ? r.needed : Number(r.needed);
  if (r.met) return 100;
  if (!Number.isFinite(cur) || !Number.isFinite(need)) return 0;
  if (INVERTED.test(r.key)) {
    if (cur <= 0) return 100;
    return Math.max(0, Math.min(99, Math.round((need / cur) * 100)));
  }
  if (need <= 0) return 0;
  return Math.max(0, Math.min(99, Math.round((cur / need) * 100)));
}

export function missingRequirements(next: NextStep | null | undefined): Requirement[] {
  return (next?.requirements || []).filter((r) => !r.met);
}

// tool results carry {autonomy} at the top or under metadata
export interface AutonomyMeta {
  action_id?: string;
  grant_id?: string | null;
  level?: number | null;
  level_label?: string | null;
  mode?: string | null;
  status?: string | null;
  action_key?: string | null;
  approval_id?: string | null;
}

export function autonomyMetaOf(x: unknown): AutonomyMeta | null {
  if (!x || typeof x !== 'object') return null;
  const o = x as Record<string, unknown>;
  const direct = o.autonomy;
  if (direct && typeof direct === 'object') return direct as AutonomyMeta;
  const md = o.metadata;
  if (md && typeof md === 'object') {
    const a = (md as Record<string, unknown>).autonomy;
    if (a && typeof a === 'object') return a as AutonomyMeta;
  }
  return null;
}

export function autonomyBadgeText(m: AutonomyMeta): string {
  const label = m.level_label || (typeof m.level === 'number' ? levelMeta(m.level).label : 'Managed');
  if (m.status === 'pending') return `${label}, waiting in Approvals`;
  if (m.status === 'watching') return `${label}, not run`;
  if (m.status === 'blocked') return `${label}, blocked`;
  if (m.status === 'rejected') return `${label}, rejected`;
  if (m.status === 'executed' || m.status === 'approved' || m.status === 'edited') return `${label}, done`;
  return label;
}

export function autonomyBadgeHref(m: AutonomyMeta): string {
  if (m.status === 'pending') return '/approvals';
  if (m.grant_id) return `/autonomy/${encodeURIComponent(m.grant_id)}`;
  return '/autonomy';
}

export function isActionGate(gateKind: string | null | undefined): boolean {
  return typeof gateKind === 'string' && gateKind.startsWith('action:');
}

export function relTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return '';
  const diff = Date.now() - t;
  const future = diff < 0;
  const m = Math.floor(Math.abs(diff) / 60000);
  let s: string;
  if (m < 1) s = future ? 'in under a minute' : 'just now';
  else if (m < 60) s = `${m}m`;
  else if (m < 60 * 24) s = `${Math.floor(m / 60)}h`;
  else s = `${Math.floor(m / 1440)}d`;
  if (m < 1) return s;
  return future ? `in ${s}` : `${s} ago`;
}

export function daysSince(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}

// ---- thresholds for moving up, per action type

export type Policy = Record<string, unknown>;

export interface PolicyField {
  step: 'to_asks_first' | 'to_within_limits';
  key: string;
  label: string;
  kind: 'count' | 'days' | 'pct';
  min: number;
  max: number;
}

export const POLICY_FIELDS: PolicyField[] = [
  { step: 'to_asks_first', key: 'min_reviews', label: 'Reviews needed', kind: 'count', min: 1, max: 10000 },
  { step: 'to_asks_first', key: 'min_agreement_lb', label: 'Agreement needed (%)', kind: 'pct', min: 0, max: 100 },
  { step: 'to_within_limits', key: 'min_executed', label: 'Scored actions needed', kind: 'count', min: 1, max: 100000 },
  { step: 'to_within_limits', key: 'min_accuracy_lb', label: 'Accuracy needed (%)', kind: 'pct', min: 0, max: 100 },
  { step: 'to_within_limits', key: 'min_no_edit_rate', label: 'Approved without edits (%)', kind: 'pct', min: 0, max: 100 },
  { step: 'to_within_limits', key: 'max_reject_rate', label: 'Rejected at most (%)', kind: 'pct', min: 0, max: 100 },
  { step: 'to_within_limits', key: 'max_unknown_rate', label: 'Missing outcomes at most (%)', kind: 'pct', min: 0, max: 100 },
  { step: 'to_within_limits', key: 'harm_free_days', label: 'Days without harm', kind: 'days', min: 0, max: 3650 },
  { step: 'to_within_limits', key: 'min_days_at_level', label: 'Days at Asks first', kind: 'days', min: 0, max: 3650 },
];

const fieldId = (f: PolicyField) => `${f.step}.${f.key}`;

// the effective numbers as form text, shares shown as percents
export function policyForm(effective: Policy | null | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of POLICY_FIELDS) {
    const v = ((effective?.[f.step] as Record<string, unknown> | undefined) || {})[f.key];
    out[fieldId(f)] = typeof v === 'number' ? String(f.kind === 'pct' ? Math.round(v * 1000) / 10 : v) : '';
  }
  return out;
}

// the form back into a policy override, keeping keys the form does not show
export function policyFromForm(
  form: Record<string, string>,
  current: Policy | null | undefined,
): { policy: Policy; errors: Record<string, string> } {
  const policy: Policy = JSON.parse(JSON.stringify(current || {}));
  const errors: Record<string, string> = {};
  for (const f of POLICY_FIELDS) {
    const raw = (form[fieldId(f)] ?? '').trim();
    if (raw === '') continue;
    const n = Number(raw);
    const whole = f.kind !== 'pct';
    if (!Number.isFinite(n) || n < f.min || n > f.max || (whole && !Number.isInteger(n))) {
      errors[fieldId(f)] = whole ? `A whole number from ${f.min} to ${f.max}` : 'A percent from 0 to 100';
      continue;
    }
    const step = { ...((policy[f.step] as Record<string, unknown> | undefined) || {}) };
    step[f.key] = f.kind === 'pct' ? Math.round(n * 10) / 1000 : n;
    policy[f.step] = step;
  }
  return { policy, errors };
}
