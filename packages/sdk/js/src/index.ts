/**
 * Abenix JavaScript SDK
 *
 * Drop-in client for executing agents, streaming responses, and monitoring
 * executions from any JavaScript/TypeScript application.
 *
 * Usage:
 *   import { Abenix } from '@abenix/sdk';
 *
 *   const forge = new Abenix({
 *     apiKey: 'af_your_key_here',
 *     baseUrl: 'https://api.abenix.dev',
 *   });
 *
 *   // Simple execution
 *   const result = await forge.execute('deep-research', 'Analyze market trends for EVs');
 *
 *   // Streaming execution
 *   const stream = forge.stream('deep-research', 'Analyze market trends for EVs');
 *   for await (const event of stream) {
 *     if (event.type === 'token') console.log(event.text);
 *     if (event.type === 'tool_call') console.log('Tool:', event.name);
 *     if (event.type === 'done') console.log('Cost:', event.cost);
 *   }
 *
 *   // Monitor live executions
 *   const live = await forge.executions.live();
 */

export interface ActingSubject {
  subjectType: string;
  subjectId: string;
  email?: string;
  displayName?: string;
  metadata?: Record<string, unknown>;
}

export interface AbenixConfig {
  apiKey: string;
  baseUrl?: string;
  timeout?: number;
  /** RBAC delegation: act on behalf of an end user.
   *  When set, all SDK calls send X-Abenix-Subject header so the platform
   *  can enforce row-level security on tools and queries. The API key must
   *  have `can_delegate` scope to use this. */
  actAs?: ActingSubject;
}

export type WaitMode = 'completed' | 'submitted' | 'until_gate';

export interface ExecuteOptions {
  stream?: boolean;
  maxTokens?: number;
  temperature?: number;
  context?: Record<string, unknown>;
  actAs?: ActingSubject;
  /** HITL-aware wait mode (overrides `wait`):
   *   - "completed" (default): block until terminal
   *   - "submitted": kick off, return immediately with executionId
   *   - "until_gate": block; if a HITL gate opens, return early with pausedAt
   */
  wait?: WaitMode | boolean;
}

export interface StreamEvent {
  type: 'token' | 'tool_call' | 'tool_result' | 'node_start' | 'node_complete' | 'done' | 'error';
  text?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  result?: string;
  nodeId?: string;
  toolName?: string;
  status?: string;
  durationMs?: number;
  inputTokens?: number;
  outputTokens?: number;
  cost?: number;
  message?: string;
}

export interface ApprovalRef {
  approvalId: string;
  title: string;
  payload: Record<string, unknown>;
  requiredSignoffs: number;
  expiresAt: string | null;
  gateKind: string | null;
}

export interface ExecutionResult {
  output: string;
  inputTokens: number;
  outputTokens: number;
  cost: number;
  durationMs: number;
  model: string;
  toolCalls: Array<{ name: string; arguments: Record<string, unknown>; result: string }>;
  confidenceScore?: number;
  executionId?: string;
  /** completed | failed | paused | running */
  status: string;
  pausedAt?: ApprovalRef;
  /** what started the run: schedule, webhook, manual, event, source_watch, chat, api ... */
  triggerKind?: string | null;
  triggerId?: string | null;
  triggerName?: string | null;
  startedBy?: string | null;
}

export interface ListExecutionsOptions {
  agentId?: string;
  status?: string;
  triggerKind?: string | string[];
  triggerId?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export interface Approval {
  id: string;
  agentId: string | null;
  agentExecutionId: string | null;
  title: string;
  payload: Record<string, unknown>;
  requiredSignoffs: number;
  signoffs: Array<Record<string, unknown>>;
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'returned';
  requestedBy: string | null;
  expiresAt: string | null;
  decidedAt: string | null;
  createdAt: string | null;
  gateKind: string | null;
  clientToken: string | null;
}

export interface LiveExecution {
  executionId: string;
  agentId: string;
  agentName: string;
  status: string;
  currentStep: string;
  currentTool: string;
  inputTokens: number;
  outputTokens: number;
  cost: number;
  iteration: number;
  maxIterations: number;
  confidenceScore?: number;
}

export interface Agent {
  id: string;
  name: string;
  slug: string;
  description: string;
  category?: string;
  version?: string;
  modelConfig: Record<string, unknown>;
}

export interface CognifyOptions {
  docIds?: string[];
  model?: string;
  chunkSize?: number;
  chunkOverlap?: number;
}

export interface CognifyResult {
  jobId: string;
  status: string;
  documents: number;
  message: string;
}

export interface GraphStats {
  entities: number;
  relationships: number;
  entityTypes: Record<string, number>;
}

export interface SearchOptions {
  mode?: 'vector' | 'graph' | 'hybrid';
  topK?: number;
  graphDepth?: number;
}

export interface SearchResult {
  results: Array<{ text: string; score: number; source?: string; metadata?: Record<string, unknown> }>;
  graphEntities?: Array<{ name: string; type: string; description: string }>;
}

export interface UploadDocumentOptions {
  chunkSize?: number;
  chunkOverlap?: number;
}

export class Abenix {
  private apiKey: string;
  private baseUrl: string;
  private timeout: number;
  private defaultActAs?: ActingSubject;

  public executions: ExecutionsClient;
  public agents: AgentsClient;
  public knowledge: KnowledgeClient;
  public approvals: ApprovalsClient;
  public decisions: DecisionsClient;
  public sources: SourcesClient;
  public events: EventsClient;
  public actions: ActionsClient;
  public autonomy: AutonomyClient;

  constructor(config: AbenixConfig) {
    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl || 'http://localhost:8000').replace(/\/$/, '');
    this.timeout = config.timeout || 120000;
    this.defaultActAs = config.actAs;
    this.executions = new ExecutionsClient(this);
    this.agents = new AgentsClient(this);
    this.knowledge = new KnowledgeClient(this);
    this.approvals = new ApprovalsClient(this);
    this.decisions = new DecisionsClient(this);
    this.sources = new SourcesClient(this);
    this.events = new EventsClient(this);
    this.actions = new ActionsClient(this);
    this.autonomy = new AutonomyClient(this);
  }

  /** The key's user, role and capabilities. */
  permissions(): Promise<{ user_id: string; email: string; role: string; capabilities: string[] }> {
    return platformCall(this, 'GET', '/api/me/permissions');
  }

  private _subjectHeader(actAs?: ActingSubject): Record<string, string> {
    const subject = actAs || this.defaultActAs;
    if (!subject) return {};
    return {
      'X-Abenix-Subject': JSON.stringify({
        subject_type: subject.subjectType,
        subject_id: subject.subjectId,
        email: subject.email,
        display_name: subject.displayName,
        metadata: subject.metadata,
      }),
    };
  }

  setActAs(actAs: ActingSubject | undefined): void {
    this.defaultActAs = actAs;
  }

  async execute(agentSlugOrId: string, message: string, options?: ExecuteOptions): Promise<ExecutionResult> {
    const agentId = await this._resolveAgentId(agentSlugOrId);
    const { actAs, wait, ...execOptions } = options || {};

    const body: Record<string, unknown> = {
      message,
      stream: false,
      wait: true,
      wait_timeout_seconds: Math.max(5, Math.min(1800, Math.floor((this.timeout / 1000) - 5))),
      ...execOptions,
    };
    if (typeof wait === 'string') {
      body.wait_mode = wait;
      body.wait = wait !== 'submitted';
      body.stream = false;
    } else if (wait === false) {
      body.wait = false;
    }

    const res = await this._fetch(`/api/agents/${agentId}/execute`, {
      method: 'POST',
      body: JSON.stringify(body),
      headers: this._subjectHeader(actAs),
    });

    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.error?.message || `HTTP ${res.status}`);
    }

    const data = await res.json();
    const d = data.data || {};

    if (d.status === 'paused' && d.paused_at) {
      const pa = d.paused_at;
      return {
        output: '',
        inputTokens: 0,
        outputTokens: 0,
        cost: 0,
        durationMs: 0,
        model: '',
        toolCalls: [],
        executionId: d.execution_id,
        status: 'paused',
        pausedAt: {
          approvalId: pa.approval_id || '',
          title: pa.title || '',
          payload: pa.payload || {},
          requiredSignoffs: pa.required_signoffs || 1,
          expiresAt: pa.expires_at || null,
          gateKind: pa.gate_kind || null,
        },
      };
    }

    if (typeof wait === 'string' && wait === 'submitted') {
      return {
        output: '',
        inputTokens: 0,
        outputTokens: 0,
        cost: 0,
        durationMs: 0,
        model: '',
        toolCalls: [],
        executionId: d.execution_id,
        status: d.status || 'running',
      };
    }

    return {
      output: d.output || d.output_message || '',
      inputTokens: d.input_tokens || 0,
      outputTokens: d.output_tokens || 0,
      cost: d.cost || 0,
      durationMs: d.duration_ms || 0,
      model: d.model || '',
      toolCalls: d.tool_calls || [],
      confidenceScore: d.confidence_score,
      executionId: d.execution_id,
      status: d.status || 'completed',
      triggerKind: d.trigger_kind ?? null,
      triggerId: d.trigger_id ?? null,
      triggerName: d.trigger_name ?? null,
      startedBy: d.started_by ?? null,
    };
  }

  async *stream(agentSlugOrId: string, message: string, options?: ExecuteOptions): AsyncGenerator<StreamEvent> {
    const agentId = await this._resolveAgentId(agentSlugOrId);
    const { actAs, ...execOptions } = options || {};
    const res = await this._fetch(`/api/agents/${agentId}/execute`, {
      method: 'POST',
      body: JSON.stringify({ message, stream: true, ...execOptions }),
      headers: this._subjectHeader(actAs),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      yield { type: 'error', message: body?.error?.message || `HTTP ${res.status}` };
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      yield { type: 'error', message: 'No response body' };
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let currentEvent = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim();
        } else if (line.startsWith('data: ') && currentEvent) {
          const data = JSON.parse(line.slice(6));
          yield this._mapEvent(currentEvent, data);
          currentEvent = '';
        }
      }
    }
  }

  async approve(executionId: string, gateId: string, comment = ''): Promise<void> {
    await this._fetch(`/api/executions/${executionId}/approve?gate_id=${gateId}`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'approved', comment }),
    });
  }

  async reject(executionId: string, gateId: string, comment = ''): Promise<void> {
    await this._fetch(`/api/executions/${executionId}/approve?gate_id=${gateId}`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'rejected', comment }),
    });
  }

  private async _resolveAgentId(slugOrId: string): Promise<string> {
    if (slugOrId.includes('-') && slugOrId.length > 30) return slugOrId; // UUID
    // Search first (fast path), then paginated scan (covers OOB agents
    // that may not appear in the first page of results).
    const searchRes = await this._fetch(`/api/agents?search=${encodeURIComponent(slugOrId)}&limit=5`);
    if (searchRes.ok) {
      const sd = await searchRes.json();
      const hit = sd.data?.find((a: Agent) => a.slug === slugOrId || a.id === slugOrId);
      if (hit) return hit.id;
    }
    let offset = 0;
    while (true) {
      const res = await this._fetch(`/api/agents?limit=100&offset=${offset}`);
      if (!res.ok) throw new Error('Failed to list agents');
      const data = await res.json();
      const page: Agent[] = data.data || [];
      const agent = page.find((a) => a.slug === slugOrId || a.id === slugOrId);
      if (agent) return agent.id;
      if (page.length < 100) break;
      offset += 100;
    }
    throw new Error(`Agent not found: ${slugOrId}`);
  }

  async _fetch(path: string, init?: RequestInit): Promise<Response> {
    return fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': this.apiKey,
        ...(init?.headers || {}),
      },
      signal: AbortSignal.timeout(this.timeout),
    });
  }

  private _mapEvent(event: string, data: Record<string, unknown>): StreamEvent {
    switch (event) {
      case 'token': return { type: 'token', text: data.text as string };
      case 'tool_call': return { type: 'tool_call', name: data.name as string, arguments: data.arguments as Record<string, unknown> };
      case 'tool_result': return { type: 'tool_result', name: data.name as string, result: data.result as string };
      case 'node_start': return { type: 'node_start', nodeId: data.node_id as string, toolName: data.tool_name as string };
      case 'node_complete': return { type: 'node_complete', nodeId: data.node_id as string, status: data.status as string, durationMs: data.duration_ms as number };
      case 'done': return {
        type: 'done',
        inputTokens: data.input_tokens as number,
        outputTokens: data.output_tokens as number,
        cost: data.cost as number,
        durationMs: data.duration_ms as number,
      };
      case 'error': return { type: 'error', message: data.message as string };
      default: return { type: 'error', message: `Unknown event: ${event}` };
    }
  }
}

class ExecutionsClient {
  constructor(private client: Abenix) {}

  async live(): Promise<LiveExecution[]> {
    const res = await this.client._fetch('/api/executions/live');
    const data = await res.json();
    return data.data || [];
  }

  async get(executionId: string): Promise<Record<string, unknown>> {
    const res = await this.client._fetch(`/api/executions/${executionId}`);
    const data = await res.json();
    return data.data;
  }

  /** Past runs, each with trigger_kind, trigger_id, trigger_name and started_by. */
  async list(options: ListExecutionsOptions = {}): Promise<Array<Record<string, unknown>>> {
    const q = new URLSearchParams();
    if (options.agentId) q.set('agent_id', options.agentId);
    if (options.status) q.set('status', options.status);
    if (options.triggerKind) {
      q.set('trigger_kind', Array.isArray(options.triggerKind) ? options.triggerKind.join(',') : options.triggerKind);
    }
    if (options.triggerId) q.set('trigger_id', options.triggerId);
    if (options.search) q.set('search', options.search);
    q.set('limit', String(options.limit ?? 20));
    q.set('offset', String(options.offset ?? 0));
    const res = await this.client._fetch(`/api/executions?${q.toString()}`);
    const data = await res.json();
    return data.data || [];
  }

  async replay(executionId: string): Promise<Record<string, unknown>> {
    const res = await this.client._fetch(`/api/executions/${executionId}/replay`);
    const data = await res.json();
    return data.data;
  }

  async tree(executionId: string): Promise<Record<string, unknown>> {
    const res = await this.client._fetch(`/api/executions/tree/${executionId}`);
    const data = await res.json();
    return data.data;
  }

  async pendingApprovals(): Promise<Record<string, unknown>[]> {
    const res = await this.client._fetch('/api/executions/approvals');
    const data = await res.json();
    return data.data || [];
  }
}

class AgentsClient {
  constructor(private client: Abenix) {}

  async list(): Promise<Agent[]> {
    const res = await this.client._fetch('/api/agents');
    const data = await res.json();
    return data.data || [];
  }

  async get(agentId: string): Promise<Agent> {
    const res = await this.client._fetch(`/api/agents/${agentId}`);
    const data = await res.json();
    return data.data;
  }
}

class KnowledgeClient {
  constructor(private client: Abenix) {}

  async cognify(kbId: string, options?: CognifyOptions): Promise<CognifyResult> {
    const res = await this.client._fetch(`/api/knowledge-engines/${kbId}/cognify`, {
      method: 'POST',
      body: JSON.stringify({
        doc_ids: options?.docIds,
        model: options?.model || 'claude-sonnet-4-5-20250929',
        chunk_size: options?.chunkSize || 1000,
        chunk_overlap: options?.chunkOverlap || 200,
      }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new Error(body?.error?.message || `Cognify failed: HTTP ${res.status}`);
    }

    const data = await res.json();
    return {
      jobId: data.data?.job_id || '',
      status: data.data?.status || '',
      documents: data.data?.documents || 0,
      message: data.data?.message || '',
    };
  }

  async graphStats(kbId: string): Promise<GraphStats> {
    const res = await this.client._fetch(`/api/knowledge-engines/${kbId}/graph-stats`);
    if (!res.ok) throw new Error(`Failed to get graph stats: HTTP ${res.status}`);
    const data = await res.json();
    return {
      entities: data.data?.entities || 0,
      relationships: data.data?.relationships || 0,
      entityTypes: data.data?.entity_types || {},
    };
  }

  async search(kbId: string, query: string, options?: SearchOptions): Promise<SearchResult> {
    const res = await this.client._fetch(`/api/knowledge-engines/${kbId}/search`, {
      method: 'POST',
      body: JSON.stringify({
        query,
        mode: options?.mode || 'hybrid',
        top_k: options?.topK || 5,
        graph_depth: options?.graphDepth || 2,
      }),
    });

    if (!res.ok) throw new Error(`Search failed: HTTP ${res.status}`);
    const data = await res.json();
    return {
      results: data.data?.results || [],
      graphEntities: data.data?.graph_entities,
    };
  }

  async graph(kbId: string, limit = 100): Promise<Record<string, unknown>> {
    const res = await this.client._fetch(`/api/knowledge-engines/${kbId}/graph?limit=${limit}`);
    if (!res.ok) throw new Error(`Failed to get graph: HTTP ${res.status}`);
    const data = await res.json();
    return data.data || {};
  }

  async cognifyJobs(kbId: string): Promise<Array<Record<string, unknown>>> {
    const res = await this.client._fetch(`/api/knowledge-engines/${kbId}/cognify-jobs`);
    if (!res.ok) throw new Error(`Failed to get cognify jobs: HTTP ${res.status}`);
    const data = await res.json();
    return data.data || [];
  }
}

export class AbenixDecisionError extends Error {
  constructor(public status: number, message: string, public code?: string, public details?: unknown) {
    super(message);
    this.name = 'AbenixDecisionError';
  }
}

export type DecisionOutcome = 'decided' | 'no_match' | 'missing_facts' | 'invalid_facts';

export interface DecisionResult {
  decision: { key: string; name: string; risk_tier: string };
  version: { id: string; version: number; content_hash: string; valid_from: string | null; valid_to: string | null };
  as_of: string;
  outcome: DecisionOutcome;
  result: unknown;
  applied_rules: string[];
  missing_facts: string[];
  invalid_facts: { fact: string; expected: string; got: string; value: string }[];
  trace: { rule_id: string; description: string; values_seen: Record<string, unknown> }[];
  trace_hash: string;
  evaluation_id?: string;
}

export class DecisionsClient {
  constructor(private client: Abenix) {}

  private async call<T>(method: string, path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
    const res = await this.client._fetch(path, { method, body: body === undefined ? undefined : JSON.stringify(body), headers });
    const json: any = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = typeof json?.error === 'object' && json.error ? json.error : { message: String(json?.error ?? `HTTP ${res.status}`) };
      throw new AbenixDecisionError(res.status, err.message, err.error_code, err.details);
    }
    return json?.data as T;
  }

  list(q = ''): Promise<any[]> {
    return this.call('GET', `/api/decisions${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  }

  get(key: string): Promise<any> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}`);
  }

  /** Missing facts are reported, never guessed. */
  evaluate(key: string, facts: Record<string, unknown>, opts: { asOf?: string; knownAt?: string; version?: number; trace?: boolean; persist?: boolean; idempotencyKey?: string } = {}): Promise<DecisionResult> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/evaluate`, {
      facts, as_of: opts.asOf, known_at: opts.knownAt, version: opts.version, trace: opts.trace ?? true,
      persist: opts.persist ?? false, idempotency_key: opts.idempotencyKey,
    });
  }

  evaluateBatch(key: string, items: { facts: Record<string, unknown>; as_of?: string }[], opts: { asOf?: string; version?: number } = {}): Promise<{ results: DecisionResult[]; counts: Record<string, number> }> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/evaluate-batch`, { items, as_of: opts.asOf, version: opts.version });
  }

  compare(key: string, facts: Record<string, unknown>, targets: { label?: string; version?: number; as_of?: string; known_at?: string }[]): Promise<{ results: any[]; any_difference: boolean }> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/compare`, { facts, targets });
  }

  async proposeRules(key: string, rules: unknown, note: string, mode: 'merge' | 'replace' = 'merge'): Promise<any> {
    const k = encodeURIComponent(key);
    const draft: any = await this.call('POST', `/api/decisions/${k}/versions`, { note });
    await this.call('POST', `/api/decisions/${k}/import`, { payload: rules, mode, version: draft.version }, { 'If-Match': draft.etag });
    return this.call('POST', `/api/decisions/${k}/versions/${draft.version}/propose`, { note });
  }

  export(key: string, version?: number): Promise<any> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/export${version ? `?version=${version}` : ''}`);
  }

  referenceSets(): Promise<any[]> {
    return this.call('GET', '/api/decision-reference-sets');
  }

  update(key: string, fields: { name?: string; description?: string; riskTier?: string; tags?: string[]; logMode?: string }): Promise<any> {
    const body: Record<string, unknown> = {};
    if (fields.name !== undefined) body.name = fields.name;
    if (fields.description !== undefined) body.description = fields.description;
    if (fields.riskTier !== undefined) body.risk_tier = fields.riskTier;
    if (fields.tags !== undefined) body.tags = fields.tags;
    if (fields.logMode !== undefined) body.log_mode = fields.logMode;
    return this.call('PATCH', `/api/decisions/${encodeURIComponent(key)}`, body);
  }

  /** A draft copied from fromVersion, or from the version in force. Carries an etag for saves. */
  newDraft(key: string, opts: { note?: string; fromVersion?: number } = {}): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/versions`, { note: opts.note ?? '', from_version: opts.fromVersion });
  }

  /** With an etag a stale save is refused with STALE_DRAFT. */
  saveDraft(key: string, version: number, fields: {
    etag?: string; authoring?: unknown; content?: unknown; validFrom?: string; validTo?: string;
    clearValidFrom?: boolean; clearValidTo?: boolean; changeNote?: string; provenance?: unknown;
  }): Promise<any> {
    const body: Record<string, unknown> = { clear_valid_from: !!fields.clearValidFrom, clear_valid_to: !!fields.clearValidTo };
    if (fields.authoring !== undefined) body.authoring = fields.authoring;
    if (fields.content !== undefined) body.content = fields.content;
    if (fields.validFrom !== undefined) body.valid_from = fields.validFrom;
    if (fields.validTo !== undefined) body.valid_to = fields.validTo;
    if (fields.changeNote !== undefined) body.change_note = fields.changeNote;
    if (fields.provenance !== undefined) body.provenance = fields.provenance;
    return this.call('PUT', `/api/decisions/${encodeURIComponent(key)}/versions/${version}`, body, fields.etag ? { 'If-Match': fields.etag } : undefined);
  }

  importRules(key: string, version: number, rules: unknown, opts: { mode?: 'merge' | 'replace'; etag?: string } = {}): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/import`, { payload: rules, mode: opts.mode ?? 'merge', version },
      opts.etag ? { 'If-Match': opts.etag } : undefined);
  }

  /** Validates and sends a draft for sign-off under the decision's risk tier. */
  propose(key: string, version: number, note = ''): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/propose`, { note });
  }

  withdraw(key: string, version: number): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/withdraw`);
  }

  validate(key: string, version: number): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/validate`);
  }

  publish(key: string, version: number, opts: { expectedCurrent?: number } = {}): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/publish`, { expected_current: opts.expectedCurrent });
  }

  publishPlan(key: string, version: number): Promise<any> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/publish-plan`);
  }

  diff(key: string, a: number, b: number): Promise<any> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/diff?a=${a}&b=${b}`);
  }
}

export class AbenixError extends Error {
  constructor(public status: number, message: string, public code?: string, public details?: unknown) {
    super(message);
    this.name = 'AbenixError';
  }
}

async function platformCall<T>(client: Abenix, method: string, path: string, body?: unknown): Promise<T> {
  const res = await client._fetch(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
  const json: any = await res.json().catch(() => ({}));
  if (!res.ok) {
    const raw = json?.error ?? json?.detail;
    const err = typeof raw === 'object' && raw && !Array.isArray(raw) ? raw : { message: Array.isArray(raw) ? raw.map((x: any) => x?.msg ?? String(x)).join('; ') : String(raw ?? `HTTP ${res.status}`) };
    throw new AbenixError(res.status, err.message, err.error_code, err.details);
  }
  return json?.data as T;
}

/** Source Watch: watched pages and feeds, their snapshots and the changes found between them. */
export class SourcesClient {
  constructor(private client: Abenix) {}

  list(q = ''): Promise<any[]> {
    return platformCall(this.client, 'GET', `/api/sources${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  }

  get(sourceId: string): Promise<any> {
    return platformCall(this.client, 'GET', `/api/sources/${sourceId}`);
  }

  create(body: { name: string; url: string; kind?: string; description?: string; cadence_minutes?: number; selector?: string; jurisdiction?: string; tags?: string[]; risk_tier?: string; active?: boolean }): Promise<any> {
    return platformCall(this.client, 'POST', '/api/sources', { kind: 'html', ...body });
  }

  update(sourceId: string, fields: Record<string, unknown>): Promise<any> {
    return platformCall(this.client, 'PATCH', `/api/sources/${sourceId}`, fields);
  }

  delete(sourceId: string): Promise<any> {
    return platformCall(this.client, 'DELETE', `/api/sources/${sourceId}`);
  }

  pause(sourceId: string, reason = ''): Promise<any> {
    return platformCall(this.client, 'POST', `/api/sources/${sourceId}/pause`, { reason });
  }

  resume(sourceId: string): Promise<any> {
    return platformCall(this.client, 'POST', `/api/sources/${sourceId}/resume`);
  }

  checkNow(sourceId: string): Promise<any> {
    return platformCall(this.client, 'POST', `/api/sources/${sourceId}/check-now`);
  }

  changes(limit = 50): Promise<any[]> {
    return platformCall(this.client, 'GET', `/api/sources/changes?limit=${limit}`);
  }

  change(changeId: string): Promise<any> {
    return platformCall(this.client, 'GET', `/api/sources/changes/${changeId}`);
  }

  sourceChanges(sourceId: string, limit = 100): Promise<any[]> {
    return platformCall(this.client, 'GET', `/api/sources/${sourceId}/changes?limit=${limit}`);
  }

  snapshot(snapshotId: string, opts: { full?: boolean } = {}): Promise<any> {
    return platformCall(this.client, 'GET', `/api/sources/snapshots/${snapshotId}${opts.full ? '?full=true' : ''}`);
  }
}

/** Platform events delivered to a webhook, or used to start an agent or pipeline. */
export class EventsClient {
  constructor(private client: Abenix) {}

  catalog(): Promise<any[]> {
    return platformCall(this.client, 'GET', '/api/webhooks/catalog');
  }

  list(): Promise<any[]> {
    return platformCall(this.client, 'GET', '/api/webhooks');
  }

  /** A webhook subscription returns its signing_secret once. */
  subscribe(events: string[], opts: { url?: string; name?: string; filter?: Record<string, unknown>; targetType?: 'webhook' | 'agent' | 'pipeline'; target?: Record<string, unknown> } = {}): Promise<any> {
    if (!events.length) return Promise.reject(new Error('Pick at least one event'));
    const body: Record<string, unknown> = { events, name: opts.name ?? '', target_type: opts.targetType ?? 'webhook' };
    if (opts.url) body.url = opts.url;
    if (opts.filter) body.filter = opts.filter;
    if (opts.target) body.target = opts.target;
    return platformCall(this.client, 'POST', '/api/webhooks', body);
  }

  update(subscriptionId: string, fields: Record<string, unknown>): Promise<any> {
    return platformCall(this.client, 'PUT', `/api/webhooks/${subscriptionId}`, fields);
  }

  delete(subscriptionId: string): Promise<any> {
    return platformCall(this.client, 'DELETE', `/api/webhooks/${subscriptionId}`);
  }

  deliveries(subscriptionId: string, opts: { limit?: number; status?: string } = {}): Promise<any[]> {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 20) });
    if (opts.status) q.set('status', opts.status);
    return platformCall(this.client, 'GET', `/api/webhooks/${subscriptionId}/deliveries?${q.toString()}`);
  }

  /** True when the X-Abenix-Signature header matches the raw request body. */
  static async verifySignature(secret: string, body: string, signature: string | null | undefined): Promise<boolean> {
    if (!secret || !signature) return false;
    const enc = new TextEncoder();
    const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
    const mac = new Uint8Array(await crypto.subtle.sign('HMAC', key, enc.encode(body)));
    const want = 'sha256=' + Array.from(mac, (b) => b.toString(16).padStart(2, '0')).join('');
    const got = signature.trim();
    if (want.length !== got.length) return false;
    let diff = 0;
    for (let i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ got.charCodeAt(i);
    return diff === 0;
  }
}

export type ActionDecision = 'run' | 'wait' | 'watching' | 'blocked';

export interface ActionPrediction {
  metric?: string;
  value: number | string;
  low?: number;
  high?: number;
  horizon_s?: number;
  note?: string;
}

export interface ProposeResult {
  action_id: string;
  decision: ActionDecision;
  approval_id: string | null;
  message: string;
}

export interface ActionWaitResult {
  action_id: string;
  status: string;
  decision: ActionDecision;
  /** Use these, a reviewer may have edited them. */
  arguments: Record<string, unknown>;
  edited: boolean;
  decided_by_name: string | null;
  decision_note: string | null;
  approval_id: string | null;
  message: string;
}

/** Earned autonomy for actions an app takes itself: propose, wait for a person, report what ran and what happened. */
export class ActionsClient {
  constructor(private client: Abenix) {}

  /** Ask before acting. Only decision 'run' means go ahead. */
  propose(
    actionKey: string,
    args: Record<string, unknown> = {},
    opts: { agentId?: string; target?: string; intent?: string; prediction?: ActionPrediction } = {},
  ): Promise<ProposeResult> {
    const body: Record<string, unknown> = { action_key: actionKey, arguments: args };
    if (opts.agentId) body.agent_id = opts.agentId;
    if (opts.target !== undefined) body.target = opts.target;
    if (opts.intent) body.intent = opts.intent;
    if (opts.prediction) body.prediction = opts.prediction;
    return platformCall(this.client, 'POST', '/api/autonomy/actions/propose', body);
  }

  /** Block until a person decides or the timeout fires. */
  async wait(actionId: string, opts: { timeoutSeconds?: number } = {}): Promise<ActionWaitResult> {
    const deadline = Math.max(1, opts.timeoutSeconds ?? 60);
    let elapsed = 0;
    let last = {} as ActionWaitResult;
    while (elapsed < deadline) {
      const chunk = Math.min(120, deadline - elapsed);
      last = await platformCall<ActionWaitResult>(this.client, 'GET', `/api/autonomy/actions/${actionId}/wait?timeout_s=${chunk}`);
      if (last?.decision !== 'wait') return last;
      elapsed += chunk;
    }
    return last;
  }

  /** Say the action ran, or failed. Starts the outcome clock when the action type has a probe. */
  executed(actionId: string, ok = true, opts: { resultPreview?: string } = {}): Promise<any> {
    const body: Record<string, unknown> = { ok };
    if (opts.resultPreview !== undefined) body.result_preview = opts.resultPreview;
    return platformCall(this.client, 'POST', `/api/autonomy/actions/${actionId}/executed`, body);
  }

  /** What actually happened. Scored against the prediction band. */
  reportOutcome(actionId: string, value: number | string, opts: { note?: string } = {}): Promise<any> {
    const body: Record<string, unknown> = { value, source: 'api' };
    if (opts.note) body.note = opts.note;
    return platformCall(this.client, 'POST', `/api/autonomy/actions/${actionId}/outcome`, body);
  }

  /** Flag that the action did harm. Drops the agent to Asks first at once. */
  flagHarm(actionId: string, note: string): Promise<any> {
    if (!note.trim()) return Promise.reject(new Error('Say what went wrong.'));
    return platformCall(this.client, 'POST', `/api/autonomy/actions/${actionId}/harm`, { note });
  }

  /** One action with its card, outcome and score. */
  get(actionId: string): Promise<any> {
    return platformCall(this.client, 'GET', `/api/autonomy/actions/${actionId}`);
  }
}

/** Read the autonomy ladder: levels, track records and the actions behind them. */
export class AutonomyClient {
  constructor(private client: Abenix) {}

  overview(): Promise<any> {
    return platformCall(this.client, 'GET', '/api/autonomy/overview');
  }

  grant(grantId: string): Promise<any> {
    return platformCall(this.client, 'GET', `/api/autonomy/grants/${grantId}`);
  }

  grantActions(grantId: string, opts: { status?: string; limit?: number; before?: string } = {}): Promise<{ items: any[]; next_before: string | null }> {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 50) });
    if (opts.status) q.set('status', opts.status);
    if (opts.before) q.set('before', opts.before);
    return platformCall(this.client, 'GET', `/api/autonomy/grants/${grantId}/actions?${q.toString()}`);
  }
}

export class ApprovalsClient {
  constructor(private client: Abenix) {}

  private _normalize(raw: Record<string, unknown>): Approval {
    return {
      id: raw.id as string,
      agentId: (raw.agent_id as string | null) ?? null,
      agentExecutionId: (raw.agent_execution_id as string | null) ?? null,
      title: (raw.title as string) || '',
      payload: (raw.payload as Record<string, unknown>) || {},
      requiredSignoffs: (raw.required_signoffs as number) || 1,
      signoffs: (raw.signoffs as Array<Record<string, unknown>>) || [],
      status: (raw.status as Approval['status']) || 'pending',
      requestedBy: (raw.requested_by as string | null) ?? null,
      expiresAt: (raw.expires_at as string | null) ?? null,
      decidedAt: (raw.decided_at as string | null) ?? null,
      createdAt: (raw.created_at as string | null) ?? null,
      gateKind: (raw.gate_kind as string | null) ?? null,
      clientToken: (raw.client_token as string | null) ?? null,
    };
  }

  async list(opts?: {
    status?: 'pending' | 'approved' | 'denied' | 'expired';
    executionId?: string;
    agentId?: string;
    kind?: string;
    limit?: number;
  }): Promise<Approval[]> {
    const params = new URLSearchParams();
    if (opts?.status) params.set('status', opts.status);
    if (opts?.executionId) params.set('execution_id', opts.executionId);
    if (opts?.agentId) params.set('agent_id', opts.agentId);
    if (opts?.kind) params.set('kind', opts.kind);
    params.set('limit', String(opts?.limit ?? 200));
    const res = await this.client._fetch(`/api/approvals?${params.toString()}`);
    if (!res.ok) throw new Error(`Failed to list approvals: HTTP ${res.status}`);
    const data = await res.json();
    return (data.data || []).map((row: Record<string, unknown>) => this._normalize(row));
  }

  async get(approvalId: string): Promise<Approval> {
    const res = await this.client._fetch(`/api/approvals/${approvalId}`);
    if (!res.ok) throw new Error(`Approval not found: ${approvalId}`);
    const data = await res.json();
    return this._normalize(data.data || {});
  }

  async create(
    title: string,
    payload: Record<string, unknown>,
    options?: {
      requiredSignoffs?: number;
      expiresSeconds?: number;
      gateKind?: string;
      agentId?: string;
      agentExecutionId?: string;
      clientToken?: string;
    },
  ): Promise<Approval> {
    const body: Record<string, unknown> = {
      title,
      payload,
      required_signoffs: options?.requiredSignoffs ?? 1,
      expires_seconds: options?.expiresSeconds ?? 86400,
    };
    if (options?.gateKind) body.gate_kind = options.gateKind;
    if (options?.agentId) body.agent_id = options.agentId;
    if (options?.agentExecutionId) body.agent_execution_id = options.agentExecutionId;
    if (options?.clientToken) body.client_token = options.clientToken;
    const res = await this.client._fetch('/api/approvals', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.error?.message || `HTTP ${res.status}`);
    }
    const data = await res.json();
    return this._normalize(data.data || {});
  }

  /** Send it back to the requester with what needs to change. A decision version returns to draft. */
  returnForChanges(approvalId: string, reason: string, options?: { clientToken?: string }): Promise<Approval> {
    if (!reason.trim()) return Promise.reject(new Error('Say what needs to change, so the requester can correct it.'));
    return this.signoff(approvalId, 'return', { reason, clientToken: options?.clientToken });
  }

  async signoff(
    approvalId: string,
    decision: 'approve' | 'deny' | 'return',
    options?: { reason?: string; clientToken?: string; editedArguments?: Record<string, unknown> },
  ): Promise<Approval> {
    const body: Record<string, unknown> = {
      decision,
      reason: options?.reason || '',
    };
    if (options?.clientToken) body.client_token = options.clientToken;
    // action approvals only, the agent runs with these values instead
    if (options?.editedArguments) body.edited_arguments = options.editedArguments;
    const res = await this.client._fetch(`/api/approvals/${approvalId}/signoff`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.error?.message || `HTTP ${res.status}`);
    }
    const data = await res.json();
    return this._normalize(data.data || {});
  }

  approve(approvalId: string, options?: { reason?: string; clientToken?: string; editedArguments?: Record<string, unknown> }): Promise<Approval> {
    return this.signoff(approvalId, 'approve', options);
  }

  deny(approvalId: string, options?: { reason?: string; clientToken?: string }): Promise<Approval> {
    return this.signoff(approvalId, 'deny', options);
  }

  /**
   * Block until the approval leaves pending status or the timeout fires.
   * Uses the server's /wait long-poll under the hood for efficiency.
   */
  async waitFor(
    approvalId: string,
    options?: { timeoutSeconds?: number; pollSeconds?: number },
  ): Promise<Approval> {
    const totalDeadline = Math.max(1, options?.timeoutSeconds ?? 60);
    const pollMs = Math.max(0, (options?.pollSeconds ?? 2) * 1000);
    let elapsed = 0;
    let last: Approval | null = null;
    while (elapsed < totalDeadline) {
      const chunk = Math.min(120, totalDeadline - elapsed);
      const res = await this.client._fetch(
        `/api/approvals/${approvalId}/wait?timeout_seconds=${chunk}`,
      );
      if (!res.ok) throw new Error(`Wait failed: HTTP ${res.status}`);
      const data = await res.json();
      last = this._normalize(data.data || {});
      if (last.status !== 'pending') return last;
      elapsed += chunk;
      if (pollMs > 0 && elapsed < totalDeadline) {
        await new Promise((r) => setTimeout(r, pollMs));
      }
    }
    return last as Approval;
  }

  /**
   * Stream approval lifecycle events for the tenant.
   * Yields {event, data} pairs as approvals appear and resolve.
   */
  async *subscribe(): AsyncGenerator<{ event: string; data: Record<string, unknown> }> {
    const res = await this.client._fetch(
      '/api/notifications/stream?types=approval_pending,approval_resolved',
      { headers: { Accept: 'text/event-stream' } },
    );
    if (!res.ok || !res.body) throw new Error(`Subscribe failed: HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let currentEvent = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line.startsWith('event: ')) currentEvent = line.slice(7).trim();
        else if (line.startsWith('data: ') && currentEvent) {
          try {
            yield { event: currentEvent, data: JSON.parse(line.slice(6)) };
          } catch {
            /* ignore malformed line */
          }
          currentEvent = '';
        }
      }
    }
  }

  /** Set or clear the tenant-level approval webhook URL (admin only). */
  async configureWebhook(opts: { url?: string | null; secret?: string | null }): Promise<{ url: string | null; hasSecret: boolean }> {
    const res = await this.client._fetch('/api/approvals/webhooks', {
      method: 'PUT',
      body: JSON.stringify({ url: opts.url ?? null, secret: opts.secret ?? null }),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.error?.message || `HTTP ${res.status}`);
    }
    const data = await res.json();
    return { url: data.data?.url ?? null, hasSecret: !!data.data?.has_secret };
  }
}

export default Abenix;
