import { apiFetch, type ApiErrorDetail } from '@/lib/api-client';

// Shapes follow the governed self-improvement build contract.

export type Severity = 'low' | 'medium' | 'high';
export type ClusterState = 'open' | 'proposing' | 'proposed' | 'fixed' | 'dismissed';
export type CaseState = 'accepted' | 'suggested' | 'dropped';

export interface LessonRow {
  id: string;
  source: string;
  source_label: string;
  polarity: 'negative' | 'positive';
  input_text: string;
  output_text: string;
  expected: string | null;
  note: string | null;
  failure_code: string | null;
  tool_name: string | null;
  execution_id: string | null;
  cluster_id?: string | null;
  case_id?: string | null;
  by_user_name: string | null;
  created_at: string | null;
}

export interface ProposalRow {
  id: string;
  agent: { id: string; name: string };
  cluster: { id: string; title: string } | null;
  change_kind: string;
  change_label: string;
  diff: Record<string, unknown>;
  rationale: string;
  risk: string;
  state: string;
  state_label: string;
  progress: Record<string, unknown>;
  proof: Record<string, unknown> | null;
  approval_id: string | null;
  released_revision_id: string | null;
  watch_until: string | null;
  watch_result: Record<string, unknown> | null;
  created_at: string | null;
}

export interface ClusterRow {
  id: string;
  agent: { id: string; name: string };
  title: string;
  summary: string;
  count: number;
  negative_count: number;
  severity: Severity;
  trend: number[];
  state: ClusterState;
  last_lesson_at: string | null;
  examples: LessonRow[];
  proposal: ProposalRow | null;
}

export interface ClusterDetail extends ClusterRow {
  lessons: LessonRow[];
  next_before: string | null;
  can_manage: boolean;
}

export interface Assertion {
  type: string;
  [key: string]: unknown;
}

export interface CaseRow {
  id: string;
  suite_id: string;
  name: string;
  input_message: string;
  assertions: Assertion[];
  reference_output: string | null;
  tags?: string[];
  state: CaseState;
  source_lesson_id: string | null;
  lesson_title: string | null;
}

export interface AgentImprovements {
  agent: { id: string; name: string };
  can_manage: boolean;
  clusters: ClusterRow[];
  suggested_cases: CaseRow[];
  proposals: ProposalRow[];
  releases: ProposalRow[];
  counts: { good_examples: number; closed_clusters: number; waiting_to_group: number };
  gate?: GateState;
}

export interface GateState {
  suite_id: string | null;
  gating: boolean;
  accepted: number;
  failing: number | null;
  last_run_at: string | null;
}

export interface OverviewAgent {
  agent: { id: string; name: string };
  open_clusters: number;
  open_lessons: number;
  worst_severity: Severity;
  trend: number[];
  last_lesson_at: string | null;
}

export interface Overview {
  counts: {
    open_lessons: number;
    open_clusters: number;
    proposals_waiting: number;
    releases_watching: number;
    rolled_back_30d: number;
  };
  agents: OverviewAgent[];
  total_agents: number;
}

export interface FeedbackResult {
  id: string;
  lesson_id: string | null;
  agent_id: string;
  rating: 1 | -1;
  can_view_lessons: boolean;
}

export interface FeedbackTarget {
  executionId?: string | null;
  messageId?: string | null;
  conversationId?: string | null;
  agentId?: string | null;
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

export const improvementsApi = {
  overview: (q?: string) => get<Overview>(`/overview${q ? `?q=${enc(q)}` : ''}`),
  agent: (agentId: string) => get<AgentImprovements>(`/agents/${enc(agentId)}`),
  cluster: (id: string, before?: string | null) =>
    get<ClusterDetail>(`/clusters/${enc(id)}${before ? `?before=${enc(before)}` : ''}`),
  dismiss: (id: string, reason: string) => send<ClusterRow>('POST', `/clusters/${enc(id)}/dismiss`, { reason }),
  feedback: (t: FeedbackTarget, rating: 1 | -1, correction?: string) =>
    send<FeedbackResult>('POST', '/feedback', {
      execution_id: t.executionId || undefined,
      message_id: t.messageId || undefined,
      conversation_id: t.conversationId || undefined,
      agent_id: t.agentId || undefined,
      rating,
      correction: correction?.trim() || undefined,
    }),
  note: (body: { agent_id?: string; execution_id?: string; note: string; expected?: string }) =>
    send<{ lesson_id: string; agent_id: string }>('POST', '/lessons', body),
  acceptCase: (id: string) => send<CaseRow>('POST', `/cases/${enc(id)}/accept`),
  dropCase: (id: string) => send<CaseRow>('POST', `/cases/${enc(id)}/drop`),
  patchCase: (id: string, body: Partial<Pick<CaseRow, 'name' | 'input_message' | 'reference_output' | 'assertions'>>) =>
    send<CaseRow>('PATCH', `/cases/${enc(id)}`, body),
  bulkCases: (ids: string[], action: 'accept' | 'drop') =>
    send<{ done: CaseRow[]; skipped: Array<{ id: string; reason: string }> }>('POST', '/cases/bulk', { ids, action }),
  setGate: (agentId: string, gating: boolean) => send<GateState>('PUT', `/agents/${enc(agentId)}/gate`, { gating }),
  sample: () => send<Record<string, unknown>>('POST', '/sample'),
};

// ---- helpers

export const SEVERITY_META: Record<Severity, { label: string; text: string; bg: string; border: string }> = {
  high: { label: 'High', text: 'text-rose-300', bg: 'bg-rose-500/15', border: 'border-rose-500/40' },
  medium: { label: 'Medium', text: 'text-amber-300', bg: 'bg-amber-500/15', border: 'border-amber-500/40' },
  low: { label: 'Low', text: 'text-slate-300', bg: 'bg-slate-500/15', border: 'border-slate-500/40' },
};

export function severityMeta(s: string | null | undefined) {
  return SEVERITY_META[(s as Severity) in SEVERITY_META ? (s as Severity) : 'low'];
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// chat keeps local ids for messages it has not saved yet
export function isServerId(id: string | null | undefined): boolean {
  return !!id && UUID_RE.test(id);
}

export function plural(n: number, one: string, many?: string): string {
  return `${n} ${n === 1 ? one : many || `${one}s`}`;
}

// "up", "down" or "flat", comparing the last week with the one before
export function trendDirection(series: number[] | undefined): 'up' | 'down' | 'flat' {
  const s = series || [];
  if (s.length < 2) return 'flat';
  const half = Math.floor(s.length / 2);
  const before = s.slice(0, half).reduce((a, b) => a + b, 0);
  const after = s.slice(half).reduce((a, b) => a + b, 0);
  if (after > before) return 'up';
  if (after < before) return 'down';
  return 'flat';
}

export function trendText(series: number[] | undefined): string {
  const s = series || [];
  const total = s.reduce((a, b) => a + b, 0);
  if (!total) return 'Nothing new in 14 days';
  const week = s.slice(-7).reduce((a, b) => a + b, 0);
  const dir = trendDirection(s);
  const tail = dir === 'up' ? ', rising' : dir === 'down' ? ', falling' : '';
  return `${plural(week, 'new lesson')} this week${tail}`;
}

export function needsConfirmation(c: CaseRow): boolean {
  return (c.tags || []).includes('needs_confirmation');
}

// cuts at a word, never in the middle of one
export function clipWords(text: string, max: number): string {
  const t = text.replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const cut = t.slice(0, max);
  const at = cut.lastIndexOf(' ');
  return `${(at > max * 0.6 ? cut.slice(0, at) : cut).replace(/[\s,.;:]+$/, '')}…`;
}

export function checkSummary(a: Assertion): string {
  if (a.type === 'judge') return `Judged against: ${clipWords(String(a.rubric || ''), 160)}`;
  if (a.type === 'contains') return `Answer contains "${String(a.value || '')}"`;
  if (a.type === 'not_contains') return `Answer does not contain "${String(a.value || '')}"`;
  if (a.type === 'required_tools_called') return `Calls ${(a.tools as string[] | undefined)?.join(', ') || 'the tools'}`;
  return a.type.replace(/_/g, ' ');
}

// what to say before the owner turns the gate on, or null when nothing is in the way
export function gateWarning(g: GateState): string | null {
  if (g.failing && g.failing > 0) {
    return `${plural(g.failing, 'test')} ${g.failing === 1 ? 'fails' : 'fail'} right now, edits to this live agent will be refused until they pass.`;
  }
  if (g.failing === null && g.accepted > 0) {
    return 'These tests have not run yet. Edits to this live agent will be refused until a run passes.';
  }
  return null;
}
