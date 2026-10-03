export type Tier = 'low' | 'medium' | 'high' | 'critical';

export interface AgentBrief {
  id: string;
  name: string;
  slug: string;
  kind: 'agent' | 'pipeline';
  model: string;
  risk_tier: Tier;
  status: string;
}

export interface Assertion {
  type: string;
  [key: string]: any;
}

export interface AssertionField {
  key: string;
  label: string;
  kind: 'path' | 'json' | 'number' | 'bool' | 'regex' | 'select' | 'text' | 'textarea' | 'schema' | 'list' | 'model';
  required?: boolean;
  options?: string[];
}

export interface AssertionType {
  type: string;
  label: string;
  help: string;
  deterministic?: boolean;
  fields: AssertionField[];
}

export interface AssertionResult {
  type: string;
  label: string;
  passed: boolean | null;
  score?: number;
  reason: string;
  deterministic?: boolean;
  skipped?: boolean;
  model?: string;
}

export interface EvalRun {
  id: string;
  suite_id: string;
  agent_id: string | null;
  config_hash: string | null;
  agent_revision: number | null;
  model: string | null;
  model_override: boolean;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  score: number | null;
  threshold: number;
  threshold_met: boolean | null;
  total: number;
  passed: number;
  failed: number;
  errored: number;
  triggered_by: 'manual' | 'schedule' | 'model_change' | 'publish_gate';
  cost: number;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface EvalCase {
  id: string;
  suite_id: string;
  name: string;
  input_message: string;
  context: Record<string, any>;
  assertions: Assertion[];
  weight: number;
  tags: string[];
  source_execution_id: string | null;
  reference_output: string | null;
  last_result?: { passed: boolean; score: number; status: string; run_id: string; execution_id: string | null } | null;
}

export interface GateSuite {
  suite_id: string;
  name: string;
  threshold: number;
  run_id: string | null;
  score: number | null;
  failing_cases: string[];
  state: 'passed' | 'failed' | 'not_run';
}

export interface Gate {
  allowed: boolean;
  required: boolean;
  message: string;
  suites: GateSuite[];
}

export interface Suite {
  id: string;
  name: string;
  description: string;
  agent_id: string;
  gating: boolean;
  pass_threshold: number;
  schedule_cron: string | null;
  next_run_at: string | null;
  rerun_on_model_change: boolean;
  concurrency: number;
  judge_model: string | null;
  created_at: string | null;
  agent: AgentBrief | null;
}

export interface SuiteRow extends Suite {
  case_count: number;
  last_run: EvalRun | null;
  active_run: EvalRun | null;
  trend: { run_id: string; score: number | null; at: string | null }[];
  current_version_evaluated: boolean;
}

export interface SuiteDetail extends Suite {
  cases: EvalCase[];
  runs: EvalRun[];
  current_config_hash: string | null;
  gate: Gate | null;
}

export interface EvalResult {
  id: string;
  case_id: string | null;
  case_name: string;
  execution_id: string | null;
  status: string;
  passed: boolean;
  score: number;
  assertion_results: AssertionResult[];
  output_excerpt: string | null;
  duration_ms: number | null;
  cost: number;
  error: string | null;
}

export interface CompareRow {
  case_id: string | null;
  case_name: string;
  before?: { passed: boolean; score: number };
  after?: { passed: boolean; score: number };
  score_delta?: number;
}

export interface Comparison {
  regressions: CompareRow[];
  improvements: CompareRow[];
  still_failing: CompareRow[];
  still_passing: CompareRow[];
  added: CompareRow[];
  removed: CompareRow[];
  counts: Record<string, number>;
}

export interface RunDetail extends EvalRun {
  suite: { id: string; name: string } | null;
  agent: AgentBrief | null;
  done: number;
  results: EvalResult[];
  comparison: (Comparison & { base_run: EvalRun }) | null;
}

export const TRIGGER_LABEL: Record<EvalRun['triggered_by'], string> = {
  manual: 'Run by hand',
  schedule: 'Scheduled',
  model_change: 'Model changed',
  publish_gate: 'Publish gate',
};

export const SCHEDULES: { label: string; cron: string | null }[] = [
  { label: 'Only when I run it', cron: null },
  { label: 'Every day at 06:00 UTC', cron: '0 6 * * *' },
  { label: 'Weekdays at 06:00 UTC', cron: '0 6 * * 1-5' },
  { label: 'Mondays at 06:00 UTC', cron: '0 6 * * 1' },
  { label: 'Every 6 hours', cron: '0 */6 * * *' },
];

export function pct(v: number | null | undefined): string {
  return v == null ? '–' : `${Math.round(v * 100)}%`;
}

export function shortHash(h: string | null | undefined): string {
  return h ? h.slice(0, 8) : '–';
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' });
}

export function runVerdict(r: EvalRun): { label: string; cls: string } {
  if (r.status === 'queued' || r.status === 'running') return { label: r.status === 'queued' ? 'Queued' : 'Running', cls: 'text-sky-300 bg-sky-500/10 border-sky-500/30' };
  if (r.status === 'cancelled') return { label: 'Cancelled', cls: 'text-slate-300 bg-slate-500/10 border-slate-500/30' };
  if (r.status === 'failed') return { label: 'Could not run', cls: 'text-amber-300 bg-amber-500/10 border-amber-500/30' };
  return r.threshold_met
    ? { label: 'Passed', cls: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30' }
    : { label: 'Below threshold', cls: 'text-rose-300 bg-rose-500/10 border-rose-500/30' };
}

// mirrors eval_assertions.validate on the API so the builder can flag fields as you type
export function fieldProblem(f: AssertionField, v: any): string | null {
  const empty = v === undefined || v === null || (typeof v === 'string' && !v.trim()) || (Array.isArray(v) && v.length === 0);
  if (empty) return f.required && f.kind !== 'json' ? `${f.label} is required.` : null;
  if (f.kind === 'regex') {
    try {
      new RegExp(String(v));
    } catch (e: any) {
      return `Not a valid pattern: ${e.message}`;
    }
  }
  if (f.kind === 'number' && (Number.isNaN(Number(v)) || Number(v) < 0)) return `${f.label} must be a number of zero or more.`;
  if (f.kind === 'path' && /\.\.|^\.$/.test(String(v))) return 'A path step is empty.';
  if (f.kind === 'schema' && (typeof v !== 'object' || Array.isArray(v))) return 'The schema must be a JSON object.';
  return null;
}
