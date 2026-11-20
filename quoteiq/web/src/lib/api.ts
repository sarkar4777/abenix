/**
 * The QuoteIQ API, reached same-origin through the /api/qq rewrite.
 * Types mirror the records the API keeps per email.
 */

export type Status = 'waiting' | 'processing' | 'success' | 'clarification' | 'escalated' | 'system_error';
export type Review = 'awaiting_review' | 'redrafting' | 'review_expired' | 'sent' | null;
export type StepState = 'pending' | 'running' | 'done' | 'failed' | 'skipped' | string;
export type LineOutcome = 'matched' | 'needs_clarification' | 'not_in_catalogue' | 'erp_record_inconsistent';

export interface Row {
  id: string;
  status: Status;
  review: Review;
  from_name: string;
  from_email: string;
  subject: string;
  line_count: number | null;
  lines_done: number | null;
  outcome: string | null;
  edited: boolean;
  error: string | null;
  processed_at: string | null;
}

export interface Stats {
  emails: number;
  processed: number;
  processing: number;
  waiting: number;
  awaiting_review: number;
  by_status: Record<'success' | 'clarification' | 'escalated' | 'system_error', { count: number; awaiting_review: number }>;
}

export interface Platform {
  staff_name: string;
  api_key_set: boolean;
  reachable: boolean;
  pipeline_registered: boolean;
  drafter_registered: boolean;
  detail: string | null;
}

export interface EmailText {
  to: string;
  subject: string;
  greeting: string;
  body: string;
  closing: string;
}

export interface Approval {
  id: string;
  status: 'pending' | 'signing' | 'approved' | 'returned' | 'denied' | 'expired' | 'withdrawn' | string;
  raised_at: string;
  expires_at: string | null;
  decided_at?: string;
}

export interface Draft {
  n: number;
  kind: 'quote' | 'clarification' | 'redraft';
  note: string | null;
  execution_id: string | null;
  created_at: string;
  ai: EmailText;
  edited: EmailText | null;
  approval: Approval | null;
  approval_error: string | null;
  raises: number;
  decision: { action: 'send' | 'ask' | 'escalate'; note: string | null; by: string; at: string; in_app: boolean } | null;
  sent: (EmailText & { at: string; by: string; edited: boolean }) | null;
  run_url: string | null;
}

export interface Price {
  requested_qty: number | null;
  quoted_qty: number;
  moq_applied: boolean;
  discount_pct: number;
  net_unit_price: number;
  line_total: number;
}

export interface Product {
  sku?: string;
  name?: string;
  standard_part_number?: string | null;
  [key: string]: unknown;
}

export interface Line {
  line_ref: number;
  outcome: LineOutcome;
  customer_reference?: string;
  reason?: string;
  understood?: Record<string, unknown>;
  filters?: Record<string, unknown>;
  candidates_total?: number | null;
  product?: Product | null;
  pricing?: {
    uom?: string;
    currency?: string;
    unit_price?: number;
    moq?: number;
    lead_time_days?: number;
    prices?: Price[];
  } | null;
  differs_on?: Record<string, unknown[]> | null;
  nearest?: Product[] | null;
  problem?: string | null;
  skus?: string[] | null;
}

export interface EscalationItem {
  customer_reference?: string;
  outcome?: string;
  reason?: string;
  problem?: string;
  skus?: string[];
  nearest_products?: Product[];
}

export interface Run {
  execution_id: string;
  started_at: string;
  finished_at: string | null;
  cost: number | null;
  duration_ms: number | null;
  steps: Record<string, StepState>;
  lines_done: number;
}

export interface Email {
  id: string;
  from_name: string;
  from_email: string;
  subject: string;
  received_text: string;
  status: Status;
  review: Review;
  error_step: 'pipeline' | 'redraft' | null;
  error: string | null;
  run: Run | null;
  redraft: { note: string; started_at: string } | null;
  processed_at: string | null;
  outcome: 'quote' | 'clarification' | 'escalation' | null;
  reason: string | null;
  lines: Line[];
  escalation: { summary?: string; reason?: string; items?: EscalationItem[] } | null;
  drafts: Draft[];
  history: { at: string; type: string; summary: string }[];
  prev_id: string | null;
  next_id: string | null;
  run_url: string | null;
  staff_name: string;
  abenix_web_url: string;
}

export interface Result<T> {
  data: T | null;
  error: string | null;
  status: number;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<Result<T>> {
  try {
    const res = await fetch(`/api/qq${path}`, {
      method,
      cache: 'no-store',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const payload = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = payload?.detail;
      const message =
        typeof detail === 'string' ? detail
          : Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg).join(', ')
            : `QuoteIQ answered ${res.status}`;
      return { data: null, error: message, status: res.status };
    }
    return { data: (payload?.data ?? null) as T, error: null, status: res.status };
  } catch {
    return { data: null, error: 'QuoteIQ could not be reached. Is the API running on port 8008?', status: 0 };
  }
}

export const api = {
  platform: () => call<Platform>('GET', '/platform'),
  stats: () => call<Stats>('GET', '/stats'),
  emails: () => call<Row[]>('GET', '/emails'),
  email: (id: string) => call<Email>('GET', `/emails/${encodeURIComponent(id)}`),
  processNext: () => call<Row>('POST', '/process-next'),
  process: (id: string) => call<Row>('POST', `/emails/${encodeURIComponent(id)}/process`),
  retry: (id: string) => call<Row>('POST', `/emails/${encodeURIComponent(id)}/retry`),
  reset: () => call<{ approvals_closed: number; approvals_left_open: number }>('POST', '/reset'),
  saveDraft: (id: string, text: Omit<EmailText, 'to'>) =>
    call<Email>('PUT', `/emails/${encodeURIComponent(id)}/draft`, text),
  revertDraft: (id: string) => call<Email>('DELETE', `/emails/${encodeURIComponent(id)}/draft/edits`),
  review: (id: string, action: 'send' | 'ask' | 'escalate', note = '') =>
    call<Email>('POST', `/emails/${encodeURIComponent(id)}/review`, { action, note }),
  raiseReview: (id: string) => call<Email>('POST', `/emails/${encodeURIComponent(id)}/raise-review`),
};

/** Tell every page to reload now, rather than at its next poll. */
export const REFRESH_EVENT = 'quoteiq:refresh';
export function refreshAll() {
  window.dispatchEvent(new Event(REFRESH_EVENT));
}
