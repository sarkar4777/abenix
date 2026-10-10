export type JobOutcome = 'ok' | 'failed' | 'skipped';

export interface JobRun {
  run_id: string;
  job_id: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  outcome: JobOutcome;
  result: unknown;
  summary: string;
  error: string | null;
  error_detail: string | null;
  trigger: 'schedule' | 'manual';
  by: string | null;
  replica: string;
}

export interface JobRow {
  id: string;
  title: string;
  what: string;
  why: string;
  group: string;
  destructive: boolean;
  confirm: string;
  sharing: string;
  schedule: string;
  interval_seconds: number | null;
  paused: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_started_at: string | null;
  last_outcome: JobOutcome | null;
  last_duration_ms: number | null;
  last_summary: string | null;
  last_result: unknown;
  last_error: string | null;
  last_error_detail: string | null;
  last_trigger: 'schedule' | 'manual' | null;
  last_by: string | null;
  last_replica: string | null;
  last_ok_at: string | null;
  last_failed_at: string | null;
  last_failed_error: string | null;
  last_skipped_at: string | null;
  run_count: number;
  fail_count: number;
  skip_count: number;
  manual_count: number;
  running: { run_id: string; started_at: string; trigger: string; by: string | null; replica: string } | null;
  history: JobRun[];
  can_run: boolean;
}

export interface JobsPayload {
  jobs: JobRow[];
  // platform operators only, jobs act on every tenant
  can_run_jobs?: boolean;
  operator_rule?: string;
  groups: string[];
  scheduler_running: boolean;
  recording: boolean;
  replica: string;
  replicas: { name: string; last_seen_at: string }[];
  now: string;
}

export interface RunNowResult {
  status: JobOutcome | 'running';
  message?: string;
  run?: JobRun;
}

export const GROUP_HELP: Record<string, string> = {
  'Runs and schedules': 'Start work on time and keep run records truthful.',
  'Approvals and review': 'Make sure nothing waiting on a person is forgotten.',
  'Learning and quality': 'Turn failures into fixes and keep quality signals complete.',
  'Retention and clean-up': 'Delete or archive data once your retention settings say it is no longer needed.',
  'Platform upkeep': 'Quotas, model health and the tamper-evident audit log.',
};

// past and future, short enough for a table cell
export function relative(iso: string | null | undefined, now: number): string {
  if (!iso) return '';
  const s = Math.round((new Date(iso).getTime() - now) / 1000);
  const a = Math.abs(s);
  let txt: string;
  if (a < 5) return s >= 0 ? 'due now' : 'just now';
  if (a < 60) txt = `${a}s`;
  else if (a < 3600) txt = `${Math.floor(a / 60)} min${a % 60 && a < 600 ? ` ${a % 60}s` : ''}`;
  else if (a < 86400) txt = `${Math.floor(a / 3600)} h${Math.floor((a % 3600) / 60) ? ` ${Math.floor((a % 3600) / 60)} min` : ''}`;
  else txt = `${Math.round(a / 86400)} d`;
  return s > 0 ? `in ${txt}` : `${txt} ago`;
}

export function absolute(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' }) : '';
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '';
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function startedBy(trigger: string | null | undefined, by: string | null | undefined): string {
  if (trigger === 'manual') return by ? `Run now by ${by}` : 'Run now';
  if (trigger === 'schedule') return 'On schedule';
  return '';
}

// a job counts as overdue when it is well past its next run and nothing recorded since
export function overdue(job: JobRow, now: number): boolean {
  if (!job.next_run_at || job.paused || job.running) return false;
  const late = now - new Date(job.next_run_at).getTime();
  const grace = Math.max(60_000, (job.interval_seconds || 60) * 2000);
  return late > grace;
}

// where the settings a job follows live
export const JOB_SETTINGS: Record<string, { href: string; label: string }> = {
  check_due_triggers: { href: '/triggers', label: 'Triggers' },
  eval_schedules: { href: '/evals', label: 'Evaluations, suite schedule' },
  watch_sources: { href: '/sources', label: 'Source Watch, check interval' },
  sweep_stale_executions: { href: '/executions?status=failed', label: 'Failed runs' },
  announce_finished_runs: { href: '/settings/notifications', label: 'Notifications' },
  dispatch_events: { href: '/settings/webhooks', label: 'Events' },
  escalate_approvals: { href: '/admin/risk', label: 'Risk & Controls, escalation time' },
  moderation_review_tick: { href: '/moderation', label: 'Moderation, review time limit' },
  observe_actions: { href: '/autonomy', label: 'Autonomy' },
  group_lessons: { href: '/improvements', label: 'Improvements' },
  improvements_tick: { href: '/improvements', label: 'Improvements' },
  improvements_watch: { href: '/improvements', label: 'Improvements' },
  score_drift_backlog: { href: '/observability', label: 'Observability' },
  moderation_retention: { href: '/moderation', label: 'Moderation, retention card' },
  lesson_retention: { href: '/improvements', label: 'Improvements, lesson retention' },
  prune_events: { href: '/settings/webhooks', label: 'Events' },
  nightly_archive: { href: '/admin/archives', label: 'Archives, retention policies' },
  ping_models: { href: '/admin/llm-settings', label: 'Model Selection' },
  link_audit_chain: { href: '/admin/audit', label: 'Audit log' },
  verify_audit_chain: { href: '/admin/audit', label: 'Audit log' },
};
