import { apiFetch, type ApiErrorDetail } from '@/lib/api-client';

// The proposal side of governed self-improvement: proof, approval, release and watch.

export type ProposalState =
  | 'drafting' | 'proving' | 'failed_proof' | 'awaiting_approval' | 'approved'
  | 'rejected' | 'released' | 'kept' | 'rolled_back' | 'superseded';

export type StepState = 'pending' | 'running' | 'done' | 'failed';

export interface ProofStep {
  key: string;
  label: string;
  state: StepState;
  done: number;
  total: number;
}

export interface Progress {
  phase?: string;
  steps?: ProofStep[];
  message?: string;
  waiting?: string;
  tokens?: number;
  started_at?: string;
  finished_at?: string;
}

export interface Scores {
  runs?: number;
  pass_rate: number | null;
  quality: number | null;
  cost_usd: number;
  latency_ms: number | null;
  // runs of this proof timed side by side, the only ones speed is judged on
  timed_runs?: number;
  tool_calls: number;
}

export const MIN_SPEED_RUNS = 10;

export interface Example {
  input: string;
  before: string;
  after: string;
  verdict: 'fixed' | 'changed' | 'same' | string;
}

export interface Proof {
  fixed: Array<{ lesson_id: string; title: string }>;
  broken: Array<{ case_id: string | null; name: string; why: string }>;
  still_failing?: Array<{ lesson_id: string; title: string }>;
  target_lessons?: number;
  cases_run?: number;
  scores?: { before: Scores; after: Scores };
  replay?: { sampled: number; changed: number; watching_effects: number };
  gating?: { suites: number; passed: boolean | null };
  examples?: Example[];
  passed_bar: boolean;
  bar_reasons: string[];
  tokens?: number;
  finished_at?: string;
}

export interface Measures {
  runs: number;
  failures: number;
  cost_avg: number;
  thumbs_total?: number;
  thumbs_down?: number;
  scored?: number;
  accurate?: number;
  cluster_lessons?: number;
  drift?: string[];
}

export interface WatchResult {
  outcome?: 'watching' | 'kept' | 'rolled_back' | 'stopped';
  started_at?: string;
  ended_at?: string;
  checked_at?: string;
  reason?: string;
  automatic?: boolean;
  rolled_back_by_name?: string;
  approved_by_name?: string;
  old?: Measures;
  new?: Measures;
  worse?: string[];
  points?: Array<{ at: string; runs: number; failure_rate: number | null; thumbs_down_rate: number | null; cost_avg: number }>;
}

export interface DiffLine {
  op: 'add' | 'remove' | 'same';
  text: string;
}

export interface Proposal {
  id: string;
  agent: { id: string | null; name: string };
  cluster: { id: string | null; title: string } | null;
  change_kind: string;
  change_label: string;
  diff: Record<string, unknown> & { preview?: { what: string; lines: DiffLine[] } };
  rationale: string;
  risk: string;
  state: ProposalState;
  state_label: string;
  progress: Progress;
  proof: Proof | null;
  approval_id: string | null;
  released_revision_id: string | null;
  watch_until: string | null;
  watch_runs_target?: number | null;
  watch_result: WatchResult | null;
  error?: string | null;
  created_at: string | null;
}

export interface Budget {
  tokens_today: number;
  tokens_limit: number;
  proofs_today: number;
  proofs_limit: number;
  auto_tokens_today?: number;
  auto_proofs_today?: number;
  // what a fix a person asks for can still use today
  tokens_left?: number;
  proofs_left?: number;
  queue_depth: number;
  stopped?: string | null;
}

export interface Res<T> {
  data: T | null;
  error: string | null;
  code?: string;
  status?: number;
}

function wrap<T>(r: { data: T | null; error: string | null; errorDetail?: ApiErrorDetail | null }): Res<T> {
  return { data: r.data, error: r.error, code: r.errorDetail?.error_code, status: r.errorDetail?.code };
}

const BASE = '/api/improvements';
const enc = encodeURIComponent;

async function get<T>(path: string): Promise<Res<T>> {
  return wrap(await apiFetch<T>(`${BASE}${path}`, { silent: true }));
}

async function send<T>(method: string, path: string, body?: unknown): Promise<Res<T>> {
  return wrap(
    await apiFetch<T>(`${BASE}${path}`, {
      method,
      body: body === undefined ? undefined : JSON.stringify(body),
      throwOnError: false,
      silent: true,
    }),
  );
}

export const proposalsApi = {
  propose: (clusterId: string) => send<Proposal>('POST', `/clusters/${enc(clusterId)}/propose`),
  get: (id: string) => get<Proposal>(`/proposals/${enc(id)}`),
  rerun: (id: string, diff?: Record<string, unknown>) =>
    send<Proposal>('POST', `/proposals/${enc(id)}/rerun`, diff ? { diff } : {}),
  requestApproval: (id: string) => send<Proposal & { approval_id: string }>('POST', `/proposals/${enc(id)}/request-approval`),
  rollback: (id: string, reason: string) => send<Proposal>('POST', `/proposals/${enc(id)}/rollback`, { reason }),
  watchCheck: (id: string) => send<Proposal>('POST', `/proposals/${enc(id)}/watch-check`),
  budget: () => get<Budget>('/budget'),
  sample: () => send<{ agent_id: string; cluster_id: string; created: boolean }>('POST', '/sample'),
};

// ---- helpers

const STATES: ProposalState[] = [
  'drafting', 'proving', 'failed_proof', 'awaiting_approval', 'approved',
  'rejected', 'released', 'kept', 'rolled_back', 'superseded',
];

export const STATE_LABEL: Record<ProposalState, string> = {
  drafting: 'Drafting a fix',
  proving: 'Proving',
  failed_proof: 'Did not pass',
  awaiting_approval: 'Waiting for approval',
  approved: 'Approved, releasing',
  rejected: 'Rejected',
  released: 'Released, being watched',
  kept: 'Kept',
  rolled_back: 'Rolled back',
  superseded: 'Replaced',
};

export const STATE_TONE: Record<ProposalState, string> = {
  drafting: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
  proving: 'border-sky-500/40 bg-sky-500/10 text-sky-300',
  failed_proof: 'border-slate-500/40 bg-slate-500/10 text-slate-300',
  awaiting_approval: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  approved: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  rejected: 'border-slate-500/40 bg-slate-500/10 text-slate-400',
  released: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300',
  kept: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  rolled_back: 'border-rose-500/40 bg-rose-500/10 text-rose-300',
  superseded: 'border-slate-500/40 bg-slate-500/10 text-slate-400',
};

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

// rows from S1's agent view and from approval payloads come in loosely typed
export function asProposal(raw: unknown): Proposal {
  const r = obj(raw);
  const state = (STATES.includes(r.state as ProposalState) ? r.state : 'drafting') as ProposalState;
  const proof = obj(r.proof);
  const cluster = obj(r.cluster);
  const agent = obj(r.agent);
  return {
    id: String(r.id || r.proposal_id || ''),
    agent: { id: (agent.id as string) ?? null, name: String(agent.name || '') },
    cluster: cluster.id || cluster.title ? { id: (cluster.id as string) ?? null, title: String(cluster.title || '') } : null,
    change_kind: String(r.change_kind || ''),
    change_label: String(r.change_label || 'Not drafted yet'),
    diff: obj(r.diff) as Proposal['diff'],
    rationale: String(r.rationale || ''),
    risk: String(r.risk || 'low'),
    state,
    state_label: String(r.state_label || STATE_LABEL[state]),
    progress: obj(r.progress) as Progress,
    proof: Object.keys(proof).length ? ({ fixed: [], broken: [], bar_reasons: [], passed_bar: false, ...proof } as Proof) : null,
    approval_id: (r.approval_id as string) ?? null,
    released_revision_id: (r.released_revision_id as string) ?? null,
    watch_until: (r.watch_until as string) ?? null,
    watch_runs_target: (r.watch_runs_target as number) ?? null,
    watch_result: r.watch_result ? (obj(r.watch_result) as WatchResult) : null,
    error: (r.error as string) ?? null,
    created_at: (r.created_at as string) ?? null,
  };
}

export function isWorking(p: Pick<Proposal, 'state'>): boolean {
  return p.state === 'drafting' || p.state === 'proving';
}

export function fixedText(proof: Proof | null | undefined): string {
  if (!proof) return 'No proof yet';
  const n = proof.fixed?.length || 0;
  const of = proof.target_lessons || n + (proof.still_failing?.length || 0);
  const broken = proof.broken?.length || 0;
  return `Fixed ${n} of ${of}, broke ${broken}`;
}

export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return 'n/a';
  return `${Math.round(x * 100)}%`;
}

export function money(x: number | null | undefined): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return 'n/a';
  if (x === 0) return '$0';
  return x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(3)}`;
}

export function seconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return 'n/a';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function rate(n: number | undefined, d: number | undefined): number | null {
  return d ? (n || 0) / d : null;
}

// a step's line, for example "Test set 4 of 6"
export function stepText(s: ProofStep): string {
  if (s.state === 'pending') return s.label;
  if (s.total > 0 && s.key !== 'done' && s.key !== 'comparing') return `${s.label} ${s.done} of ${s.total}`;
  return s.label;
}

export function watchLeft(until: string | null, now = Date.now()): string {
  if (!until) return '';
  const ms = Date.parse(until) - now;
  if (!Number.isFinite(ms)) return '';
  if (ms <= 0) return 'ends at the next check';
  const h = Math.floor(ms / 3_600_000);
  if (h < 1) return `${Math.max(1, Math.round(ms / 60000))} min left`;
  if (h < 48) return `${h} h left`;
  return `${Math.floor(h / 24)} days left`;
}

// automatic proposals only get half the day, so a spent total does not always block a person
export function budgetNote(b: Budget): { tone: 'spent' | 'auto'; text: string } | null {
  const tokens = b.tokens_left ?? b.tokens_limit - b.tokens_today;
  const proofs = b.proofs_left ?? b.proofs_limit - b.proofs_today;
  if (tokens <= 0 || proofs <= 0) {
    return { tone: 'spent', text: 'Spent for today. New proposals wait until tomorrow, or an admin can raise the budget.' };
  }
  if (b.tokens_today >= b.tokens_limit || b.proofs_today >= b.proofs_limit) {
    return { tone: 'auto', text: "Automatic proposals used their half of today's budget. Fixes you ask for still run." };
  }
  return null;
}

export function meterTone(used: number, limit: number): string {
  if (!limit) return 'bg-rose-400';
  const f = used / limit;
  if (f >= 1) return 'bg-rose-400';
  if (f >= 0.8) return 'bg-amber-400';
  return 'bg-emerald-400';
}

// word level marks for the side by side examples
export function wordDiff(before: string, after: string): Array<{ text: string; added: boolean }> {
  const a = new Set((before || '').toLowerCase().split(/\s+/).filter(Boolean));
  return (after || '').split(/(\s+)/).map((w) => ({
    text: w,
    added: /\S/.test(w) && !a.has(w.toLowerCase()),
  }));
}

// what the editor shows for each kind, and what goes back to the API
export function editableDiff(p: Proposal): string {
  const { preview: _preview, ...rest } = p.diff || {};
  void _preview;
  return JSON.stringify(rest, null, 2);
}

export function parseDiff(text: string): { diff: Record<string, unknown> | null; error: string | null } {
  try {
    const v = JSON.parse(text);
    if (!v || typeof v !== 'object' || Array.isArray(v)) return { diff: null, error: 'The change must be a JSON object.' };
    return { diff: v as Record<string, unknown>, error: null };
  } catch (e) {
    return { diff: null, error: `This is not valid JSON: ${(e as Error).message}` };
  }
}

export const CHANGE_HELP: Record<string, string> = {
  examples: 'Adds good examples to the end of the instructions.',
  prompt_edit: 'Replaces a few exact sentences in the instructions.',
  tool_config: 'Changes one setting of a tool the agent already uses.',
  tool_set: 'Adds a read-only tool or removes one.',
  model: 'Switches to another model the risk tier allows.',
  pipeline_patch: 'Patches a step of the pipeline.',
};
