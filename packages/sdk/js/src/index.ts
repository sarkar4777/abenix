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
  /** @deprecated ignored by the server, set max_tokens on the agent's model_config */
  maxTokens?: number;
  /** @deprecated ignored by the server, set temperature on the agent's model_config */
  temperature?: number;
  /** input variables for pipelines and agents */
  context?: Record<string, unknown>;
  /** continue a chat thread */
  conversationId?: string;
  /** seconds the server holds the call open, 5 to 1800 */
  waitTimeoutSeconds?: number;
  actAs?: ActingSubject;
  /** HITL-aware wait mode (overrides `wait`):
   *   - "completed" (default): block until terminal
   *   - "submitted": kick off, return immediately with executionId
   *   - "until_gate": block; if a HITL gate opens, return early with pausedAt
   */
  wait?: WaitMode | boolean;
}

export interface StreamEvent {
  /** the known events below, or any other the server sends (moderation, node_trace ...) by name */
  type: 'token' | 'tool_call' | 'tool_result' | 'node_start' | 'node_complete' | 'done' | 'error' | (string & {});
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
  /** set on done, read the run back with executions.get */
  executionId?: string;
  /** the raw event payload */
  data?: Record<string, unknown>;
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
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'returned' | 'withdrawn';
  requestedBy: string | null;
  expiresAt: string | null;
  decidedAt: string | null;
  createdAt: string | null;
  gateKind: string | null;
  clientToken: string | null;
  /** someone approved their own request, sole-operator sign-offs included */
  selfApproved: boolean;
  /** people other than the requester who may sign it, null when unknown */
  eligibleApproverCount: number | null;
  /** whether the caller can sign it now, and why not in plain words */
  canSign: boolean;
  cannotSignReason: string | null;
  /** what is being asked, in plain words */
  summary: string;
  kindLabel: string;
  /** why it was withdrawn and by whom, null when the platform did it */
  withdrawReason: string | null;
  withdrawnByName: string | null;
  /** nobody else can sign, so the requester may sign alone with a reason */
  soleOperatorAvailable: boolean;
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
  results: Array<{ content: string; score: number; source?: string; source_type?: string; metadata?: Record<string, unknown> }>;
  /** entity names the graph pass matched */
  entitiesFound: string[];
  modeUsed?: string;
  vectorCount?: number;
  graphCount?: number;
  latencyMs?: number;
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
  public improvements: ImprovementsClient;
  public lessons: LessonsClient;
  public feedback: FeedbackClient;
  public mlModels: MLModelsClient;
  public codeAssets: CodeAssetsClient;
  public killSwitches: KillSwitchesClient;
  public apiKeys: ApiKeysClient;
  public team: TeamClient;

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
    this.improvements = new ImprovementsClient(this);
    this.lessons = new LessonsClient(this);
    this.feedback = new FeedbackClient(this);
    this.mlModels = new MLModelsClient(this);
    this.codeAssets = new CodeAssetsClient(this);
    this.killSwitches = new KillSwitchesClient(this);
    this.apiKeys = new ApiKeysClient(this);
    this.team = new TeamClient(this);
  }

  /** The user this key acts as, as { user: {...} }. */
  me(): Promise<{ user: { id: string; email: string; full_name: string | null; role: string; tenant_id: string } }> {
    return platformCall(this, 'GET', '/api/me');
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
    const { actAs, wait, context, conversationId, waitTimeoutSeconds } = options || {};
    const waitTimeout = waitTimeoutSeconds ?? Math.max(5, Math.min(1800, Math.floor((this.timeout / 1000) - 5)));

    const body: Record<string, unknown> = {
      message,
      stream: false,
      wait: true,
      wait_timeout_seconds: waitTimeout,
    };
    if (context) body.context = context;
    if (conversationId) body.conversation_id = conversationId;
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
    let d = data.data || {};

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

    // an async-mode answer carries only the id, read the run until it ends
    if (d.execution_id && (d.mode === 'async' || (!d.output && !d.output_message))) {
      d = await this._pollExecution(d.execution_id, waitTimeout);
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
      executionId: d.execution_id || d.id,
      status: d.status || 'completed',
      triggerKind: d.trigger_kind ?? null,
      triggerId: d.trigger_id ?? null,
      triggerName: d.trigger_name ?? null,
      startedBy: d.started_by ?? null,
    };
  }

  private async _pollExecution(executionId: string, deadlineS: number): Promise<Record<string, any>> {
    const terminal = new Set(['completed', 'succeeded', 'failed', 'error', 'cancelled']);
    const until = Date.now() + deadlineS * 1000;
    let delay = 500;
    let last: Record<string, any> = { execution_id: executionId };
    while (Date.now() < until) {
      try {
        const r = await this._fetch(`/api/executions/${executionId}`);
        if (r.ok) {
          const row = (await r.json())?.data;
          if (row) last = { ...row, execution_id: row.id || executionId };
          if (terminal.has(String(last.status || '').toLowerCase())) return last;
        }
      } catch {
        /* keep polling until the deadline */
      }
      await new Promise((ok) => setTimeout(ok, delay));
      delay = Math.min(2000, delay * 1.5);
    }
    return last;
  }

  async *stream(agentSlugOrId: string, message: string, options?: ExecuteOptions): AsyncGenerator<StreamEvent> {
    const agentId = await this._resolveAgentId(agentSlugOrId);
    const { actAs, context, conversationId } = options || {};
    const payload: Record<string, unknown> = { message, stream: true };
    if (context) payload.context = context;
    if (conversationId) payload.conversation_id = conversationId;
    const res = await this._fetch(`/api/agents/${agentId}/execute`, {
      method: 'POST',
      body: JSON.stringify(payload),
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
    const parse = (raw: string): Record<string, unknown> => {
      try {
        const v = JSON.parse(raw);
        return v && typeof v === 'object' && !Array.isArray(v) ? v : { value: v };
      } catch {
        return { text: raw };
      }
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // the last event may arrive without a trailing newline
          buffer += decoder.decode();
          if (buffer.startsWith('data: ') && currentEvent) yield this._mapEvent(currentEvent, parse(buffer.slice(6)));
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const raw of lines) {
          const line = raw.replace(/\r$/, '');
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ') && currentEvent) {
            yield this._mapEvent(currentEvent, parse(line.slice(6)));
            currentEvent = '';
          }
        }
      }
    } finally {
      // a caller that breaks out early closes the connection too
      reader.cancel().catch(() => undefined);
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
    // a long slug with dashes used to pass for an id and 404 on execute
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(slugOrId)) return slugOrId;
    const exact = await this._fetch(`/api/agents/by-slug/${encodeURIComponent(slugOrId)}`);
    if (exact.ok) {
      const hit = (await exact.json())?.data;
      if (hit?.id) return hit.id;
    }
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
    // a form body sets its own multipart boundary
    const isForm = typeof FormData !== 'undefined' && init?.body instanceof FormData;
    return fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        'X-API-Key': this.apiKey,
        ...(init?.headers || {}),
      },
      signal: init?.signal ?? AbortSignal.timeout(this.timeout),
    });
  }

  private _mapEvent(event: string, data: Record<string, unknown>): StreamEvent {
    return { ...this._mapKnown(event, data), data };
  }

  private _mapKnown(event: string, data: Record<string, unknown>): StreamEvent {
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
        executionId: data.execution_id as string | undefined,
      };
      case 'error': return { type: 'error', message: data.message as string };
      // moderation, node_trace and newer events pass through, they are not failures
      default: return { type: event, message: data.message as string | undefined };
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

  /** Exact lookup by slug, null when there is no such agent. */
  async bySlug(slug: string): Promise<Agent | null> {
    try {
      return await platformCall<Agent>(this.client, 'GET', `/api/agents/by-slug/${encodeURIComponent(slug)}`);
    } catch (e) {
      if (e instanceof AbenixError && e.status === 404) return null;
      throw e;
    }
  }

  /** Create an agent or pipeline. Takes the same fields as POST /api/agents, including model_config. */
  create(body: Record<string, unknown>): Promise<Agent> {
    return platformCall(this.client, 'POST', '/api/agents', body);
  }

  /** A name in the body also renames the slug, leave it out to keep the slug. */
  update(agentId: string, body: Record<string, unknown>): Promise<Agent> {
    return platformCall(this.client, 'PUT', `/api/agents/${agentId}`, body);
  }
}

export interface KnowledgeDocument {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  /** processing, ready, degraded or failed */
  status: string;
  error_message: string | null;
  created_at: string | null;
}

class KnowledgeClient {
  constructor(private client: Abenix) {}

  /** Create a knowledge project and its collections, idempotently. Each collection takes name and optionally slug, description, default_visibility, vector_backend, agent_slugs and agent_permission. */
  bootstrapProject(
    slug: string,
    name: string,
    opts: { description?: string; collections?: Array<Record<string, unknown>> } = {},
  ): Promise<{
    project: { id: string; slug: string; name: string };
    collections: Array<{ id: string; name: string; slug: string; agents_granted: string[] }>;
    skipped_agents: string[];
  }> {
    return platformCall(this.client, 'POST', '/api/knowledge-projects/bootstrap', {
      slug, name, description: opts.description ?? '', collections: opts.collections ?? [],
    });
  }

  /** Add a document. It is indexed in the background, poll documents() until it is ready. */
  async upload(kbId: string, file: Blob | Uint8Array | string, filename: string, contentType?: string): Promise<KnowledgeDocument> {
    const part = file instanceof Blob ? file : new Blob([file as BlobPart], { type: contentType || 'application/octet-stream' });
    const form = new FormData();
    form.append('file', part, filename);
    return platformCall(this.client, 'POST', `/api/knowledge-bases/${kbId}/upload`, form);
  }

  /** Documents in a collection with their status. */
  documents(kbId: string): Promise<KnowledgeDocument[]> {
    return platformCall(this.client, 'GET', `/api/knowledge-bases/${kbId}/documents`);
  }

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

    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const err = body?.error ?? body?.detail;
      throw new AbenixError(res.status, err?.message || `Search failed: HTTP ${res.status}`, err?.error_code);
    }
    const data = (await res.json())?.data || {};
    return {
      results: data.results || [],
      entitiesFound: data.entities_found || [],
      modeUsed: data.mode_used,
      vectorCount: data.vector_count,
      graphCount: data.graph_count,
      latencyMs: data.latency_ms,
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

/** The review a version in force waits for after its decision's tier was raised. */
export interface DecisionReattest {
  approval_id: string;
  version: number;
  from_tier: string;
  to_tier: string;
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'returned' | 'withdrawn';
  required_signoffs: number;
}

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

  list(q = '', opts: { archived?: boolean } = {}): Promise<any[]> {
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (opts.archived) params.set('archived', '1');
    const qs = params.toString();
    return this.call('GET', `/api/decisions${qs ? `?${qs}` : ''}`);
  }

  /** available, valid, suggestion (the next free key) and archived */
  checkKey(key: string): Promise<{ available: boolean; valid: boolean; suggestion: string | null; archived?: boolean; message?: string }> {
    return this.call('GET', `/api/decisions/check-key?key=${encodeURIComponent(key)}`);
  }

  /** At a tier that asks for sign-off this needs a reason and resolves to { pending: {...} }. */
  archive(key: string, opts: { reason?: string } = {}): Promise<any> {
    return this.call('DELETE', `/api/decisions/${encodeURIComponent(key)}`, opts.reason ? { reason: opts.reason } : undefined);
  }

  /** At a tier that asks for sign-off this needs a reason and resolves to { pending: {...} }. */
  restore(key: string, opts: { reason?: string } = {}): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/restore`, opts.reason ? { reason: opts.reason } : undefined);
  }

  /** The list for a search plus how many archived decisions match too. */
  async search(q: string): Promise<{ items: any[]; archived_matches: number }> {
    const res = await this.client._fetch(`/api/decisions?q=${encodeURIComponent(q)}`, { method: 'GET' });
    const json: any = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = typeof json?.error === 'object' && json.error ? json.error : { message: `HTTP ${res.status}` };
      throw new AbenixDecisionError(res.status, err.message, err.error_code, err.details);
    }
    return { items: json?.data ?? [], archived_matches: json?.meta?.archived_matches ?? 0 };
  }

  /** Retire the version in force. At a tier that asks for sign-off this needs a reason and resolves to { pending: {...} }. */
  retire(key: string, version: number, opts: { reason?: string } = {}): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/retire`, opts.reason ? { reason: opts.reason } : undefined);
  }

  /** Delete a draft. Only its author or someone who can publish may. */
  discardDraft(key: string, version: number): Promise<any> {
    return this.call('DELETE', `/api/decisions/${encodeURIComponent(key)}/versions/${version}`);
  }

  /** Teammates who could be made approvers: active, real people who cannot approve yet. */
  approverCandidates(key: string): Promise<Array<{ id: string; name: string; email: string }>> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/approver-candidates`);
  }

  /** Put a person in the Decision reviewers set. Admins only. */
  addApprover(key: string, userId: string): Promise<any> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/approvers`, { user_id: userId });
  }

  /** Who must sign this version, who has, who could, and whether the author may sign it alone. */
  signOffInfo(key: string, version: number): Promise<any> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/versions/${version}/sign-off`);
  }

  /**
   * A decision file into a new decision, or a new draft when the key exists, with its tests.
   * Takes an export({ full: true }) file or the plain { key, name, description, risk_tier, rules, tests } shape.
   * Nothing is published. preview returns what would happen without writing.
   */
  importFile(data: unknown, opts: { preview?: boolean; asNewKey?: string; asNewName?: string } = {}): Promise<any> {
    const params = new URLSearchParams();
    if (opts.preview) params.set('preview', '1');
    if (opts.asNewKey) params.set('as_new_key', opts.asNewKey);
    if (opts.asNewName) params.set('as_new_name', opts.asNewName);
    const qs = params.toString();
    return this.call('POST', `/api/decisions/import${qs ? `?${qs}` : ''}`, typeof data === 'string' ? JSON.parse(data) : data);
  }

  /** Drop a lowering that waits for sign-off. */
  withdrawTierChange(key: string): Promise<any> {
    return this.call('DELETE', `/api/decisions/${encodeURIComponent(key)}/tier-change`);
  }

  /**
   * The review a version in force waits for after a tier raise, or null. Sign it with approvals.signoff,
   * soleOperator included when nobody else can. Once approved the version records attested_under.
   */
  async reattest(key: string): Promise<DecisionReattest | null> {
    const d: any = await this.get(key);
    return (d?.reattest as DecisionReattest | null) ?? null;
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

  /** full gives the whole decision as an abenix-decision-v1 file that importFile takes back. */
  export(key: string, version?: number, opts: { full?: boolean } = {}): Promise<any> {
    const params = new URLSearchParams();
    if (version) params.set('version', String(version));
    if (opts.full) params.set('full', '1');
    const qs = params.toString();
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/export${qs ? `?${qs}` : ''}`);
  }

  referenceSets(): Promise<any[]> {
    return this.call('GET', '/api/decision-reference-sets');
  }

  /**
   * Raising riskTier applies at once, and a version in force whose sign-off falls short gets a review,
   * returned as reattest. Lowering needs a reason, and when the current tier asks for sign-off
   * the tier stays: the result carries pending_tier_change with the approval to sign. Refused with
   * TIER_LOCKED while a version waits for sign-off.
   */
  update(key: string, fields: { name?: string; description?: string; riskTier?: string; tags?: string[]; logMode?: string; reason?: string }): Promise<any> {
    const body: Record<string, unknown> = {};
    if (fields.reason !== undefined) body.reason = fields.reason;
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

  tests(key: string): Promise<GoldenTest[]> {
    return this.call('GET', `/api/decisions/${encodeURIComponent(key)}/tests`);
  }

  /** match 'subset' needs only the expected keys to match, extra result keys are ignored. */
  addTest(key: string, name: string, facts: Record<string, unknown>, opts: { expected?: unknown; expectedOutcome?: DecisionOutcome; asOf?: string; match?: TestMatch } = {}): Promise<GoldenTest> {
    return this.call('POST', `/api/decisions/${encodeURIComponent(key)}/tests`, {
      name, facts, expected: opts.expected ?? null, expected_outcome: opts.expectedOutcome ?? 'decided', as_of: opts.asOf ?? null, match: opts.match ?? 'exact',
    });
  }

  /** Change some fields of a golden test, the rest stay as they are. */
  async updateTest(key: string, testId: string, fields: { name?: string; facts?: Record<string, unknown>; expected?: unknown; expectedOutcome?: DecisionOutcome; asOf?: string | null; match?: TestMatch }): Promise<GoldenTest> {
    const current = (await this.tests(key)).find((t) => t.id === testId);
    if (!current) throw new AbenixDecisionError(404, 'Test not found', 'NOT_FOUND');
    return this.call('PUT', `/api/decisions/${encodeURIComponent(key)}/tests/${testId}`, {
      name: fields.name ?? current.name,
      facts: fields.facts ?? current.facts ?? {},
      expected: fields.expected !== undefined ? fields.expected : current.expected,
      expected_outcome: fields.expectedOutcome ?? current.expected_outcome ?? 'decided',
      as_of: fields.asOf !== undefined ? fields.asOf : current.as_of,
      match: fields.match ?? current.match ?? 'exact',
    });
  }

  deleteTest(key: string, testId: string): Promise<{ deleted: boolean }> {
    return this.call('DELETE', `/api/decisions/${encodeURIComponent(key)}/tests/${testId}`);
  }
}

export type TestMatch = 'exact' | 'subset';

export interface GoldenTest {
  id: string;
  name: string;
  facts: Record<string, unknown>;
  expected_outcome: DecisionOutcome;
  expected: unknown;
  match: TestMatch;
  as_of: string | null;
  updated_at: string | null;
}

export class AbenixError extends Error {
  constructor(public status: number, message: string, public code?: string, public details?: unknown) {
    super(message);
    this.name = 'AbenixError';
  }
}

async function platformCall<T>(client: Abenix, method: string, path: string, body?: unknown): Promise<T> {
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const res = await client._fetch(path, {
    method,
    body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
  });
  const json: any = await res.json().catch(() => ({}));
  if (!res.ok) {
    const raw = json?.error ?? json?.detail;
    const err = typeof raw === 'object' && raw && !Array.isArray(raw) ? raw : { message: Array.isArray(raw) ? raw.map((x: any) => x?.msg ?? String(x)).join('; ') : String(raw ?? `HTTP ${res.status}`) };
    throw new AbenixError(res.status, err.message, err.error_code, err.details);
  }
  return json?.data as T;
}

/** A path (Node only), a Blob or raw bytes. */
export type FileInput = string | Blob | Uint8Array | ArrayBuffer;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// left out when a folder is zipped for upload
const SKIP_DIRS = new Set(['.git', '__pycache__', '.venv', 'venv', 'node_modules', '.mypy_cache', '.pytest_cache', '.ruff_cache']);
const FRAMEWORK_EXT: Record<string, string> = { sklearn: '.joblib', xgboost: '.joblib', onnx: '.onnx', pytorch: '.pt' };

// kept out of browser bundles, only reached with a path
function nodeImport(name: string): Promise<any> {
  return import(/* webpackIgnore: true */ /* @vite-ignore */ name);
}

let crcTable: Uint32Array | null = null;
function crc32(data: Uint8Array): number {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) crc = crcTable[(crc ^ data[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** A zip of the given files, deflated when a compressor is passed. */
export function buildZip(files: { name: string; data: Uint8Array }[], deflate?: (d: Uint8Array) => Uint8Array): Uint8Array {
  const enc = new TextEncoder();
  const chunks: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0;
  for (const f of files) {
    const name = enc.encode(f.name);
    const packed = deflate ? deflate(f.data) : f.data;
    const method = deflate ? 8 : 0;
    const crc = crc32(f.data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true);
    local.setUint16(8, method, true);
    local.setUint16(12, 33, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, packed.length, true);
    local.setUint32(22, f.data.length, true);
    local.setUint16(26, name.length, true);
    chunks.push(new Uint8Array(local.buffer), name, packed);
    const cd = new DataView(new ArrayBuffer(46));
    cd.setUint32(0, 0x02014b50, true);
    cd.setUint16(4, 20, true);
    cd.setUint16(6, 20, true);
    cd.setUint16(8, 0x0800, true);
    cd.setUint16(10, method, true);
    cd.setUint16(14, 33, true);
    cd.setUint32(16, crc, true);
    cd.setUint32(20, packed.length, true);
    cd.setUint32(24, f.data.length, true);
    cd.setUint16(28, name.length, true);
    cd.setUint32(42, offset, true);
    central.push(new Uint8Array(cd.buffer), name);
    offset += 30 + name.length + packed.length;
  }
  const cdSize = central.reduce((n, c) => n + c.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, cdSize, true);
  end.setUint32(16, offset, true);
  const parts = [...chunks, ...central, new Uint8Array(end.buffer)];
  const out = new Uint8Array(parts.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of parts) { out.set(c, at); at += c.length; }
  return out;
}

async function zipFolder(dir: string): Promise<Uint8Array> {
  const fs = await nodeImport('node:fs/promises');
  const path = await nodeImport('node:path');
  const zlib = await nodeImport('node:zlib');
  const files: { name: string; data: Uint8Array }[] = [];
  async function walk(abs: string, rel: string): Promise<void> {
    const entries = await fs.readdir(abs, { withFileTypes: true });
    entries.sort((a: any, b: any) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    for (const e of entries) {
      const childRel = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (!SKIP_DIRS.has(e.name)) await walk(path.join(abs, e.name), childRel);
      } else if (e.isFile() && e.name !== '.DS_Store') {
        files.push({ name: childRel, data: new Uint8Array(await fs.readFile(path.join(abs, e.name))) });
      }
    }
  }
  await walk(dir, '');
  if (!files.length) throw new Error(`${dir} has no files to upload`);
  return buildZip(files, (d) => new Uint8Array(zlib.deflateRawSync(d)));
}

async function readInput(input: FileInput, opts: { filename?: string; allowFolder?: boolean; fallbackName?: string }): Promise<{ blob: Blob; filename: string }> {
  if (typeof input === 'string') {
    const fs = await nodeImport('node:fs/promises');
    const path = await nodeImport('node:path');
    const st = await fs.stat(input);
    if (st.isDirectory()) {
      if (!opts.allowFolder) throw new Error(`${input} is a folder, give a file`);
      const zip = await zipFolder(input);
      return { blob: new Blob([zip as BlobPart]), filename: opts.filename || `${path.basename(path.resolve(input)) || 'code'}.zip` };
    }
    return { blob: new Blob([new Uint8Array(await fs.readFile(input)) as BlobPart]), filename: opts.filename || path.basename(input) };
  }
  const filename = opts.filename || opts.fallbackName;
  if (!filename) throw new Error('Raw bytes need a filename, for example model.joblib');
  const blob = input instanceof Blob ? input : new Blob([(input instanceof ArrayBuffer ? new Uint8Array(input) : input) as BlobPart]);
  return { blob, filename };
}

export interface MLModel {
  id: string;
  name: string;
  version: string;
  framework: string;
  description: string | null;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  /** ready, error, deployed or deleted */
  status: string;
  status_message: string | null;
  is_active: boolean;
  training_metrics: Record<string, unknown> | null;
  tags: string[] | null;
  deployments: Array<Record<string, unknown>>;
  [k: string]: unknown;
}

export interface MLUploadOptions {
  /** Needed with raw bytes unless framework is given. */
  filename?: string;
  framework?: 'sklearn' | 'xgboost' | 'onnx' | 'pytorch';
  /** Next free version when left out. */
  version?: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  /** Feature order for row input, stored on the input schema. */
  featureNames?: string[];
  outputSchema?: Record<string, unknown>;
  tags?: string[];
}

function featureSchema(names: string[], base?: Record<string, unknown>): Record<string, unknown> {
  if (base) return { ...base, features: names };
  const n = names.length;
  return {
    type: 'object',
    required: ['input_data'],
    features: names,
    properties: {
      input_data: {
        type: 'array',
        description: `Array of samples, each an array of ${n} numeric features in this order: ${names.join(', ')}.`,
        items: { type: 'array', items: { type: 'number' }, minItems: n, maxItems: n },
        'x-feature-order': names,
      },
    },
  };
}

/** The ML model registry: register, read, predict and delete. */
export class MLModelsClient {
  private ids = new Map<string, string>();
  constructor(private client: Abenix) {}

  list(): Promise<MLModel[]> {
    return platformCall<MLModel[]>(this.client, 'GET', '/api/ml-models').then((r) => r || []);
  }

  private async id(nameOrId: string): Promise<string> {
    if (UUID_RE.test(nameOrId)) return nameOrId;
    if (!this.ids.has(nameOrId)) {
      // the active version wins, otherwise the newest
      const best = new Map<string, MLModel>();
      for (const m of await this.list()) {
        const cur = best.get(m.name);
        if (!cur || (m.is_active && !cur.is_active)) best.set(m.name, m);
      }
      this.ids = new Map([...best].map(([n, m]) => [n, m.id]));
    }
    const mid = this.ids.get(nameOrId);
    if (!mid) throw new AbenixError(404, `No ML model called ${nameOrId}.`, 'NOT_FOUND');
    return mid;
  }

  /** One model version with its deployments. A name gives its active version. */
  async get(nameOrId: string): Promise<MLModel> {
    return platformCall(this.client, 'GET', `/api/ml-models/${await this.id(nameOrId)}`);
  }

  /** Register a model file as a new version of name. A file that does not load throws AbenixError 422 MODEL_LOAD_FAILED. */
  async upload(name: string, file: FileInput, opts: MLUploadOptions = {}): Promise<MLModel> {
    const fallbackName = opts.framework && FRAMEWORK_EXT[opts.framework] ? `${name}${FRAMEWORK_EXT[opts.framework]}` : undefined;
    const { blob, filename } = await readInput(file, { filename: opts.filename, fallbackName });
    const inputSchema = opts.featureNames?.length ? featureSchema(opts.featureNames.map(String), opts.inputSchema) : opts.inputSchema;
    const meta: Record<string, unknown> = { name, description: opts.description ?? '' };
    if (opts.framework) meta.framework = opts.framework;
    if (opts.version) meta.version = opts.version;
    if (inputSchema) meta.input_schema = inputSchema;
    if (opts.outputSchema) meta.output_schema = opts.outputSchema;
    if (opts.tags) meta.tags = opts.tags;
    const form = new FormData();
    form.append('metadata', JSON.stringify(meta));
    form.append('file', blob, filename);
    const model = await platformCall<MLModel>(this.client, 'POST', '/api/ml-models', form);
    this.ids.delete(name);
    if (model?.is_active) this.ids.set(name, model.id);
    return model;
  }

  /** Delete one version, or with a name and allVersions every version of it. */
  async delete(nameOrId: string, opts: { allVersions?: boolean } = {}): Promise<{ deleted: string[] }> {
    let ids: string[];
    if (opts.allVersions && !UUID_RE.test(nameOrId)) {
      ids = (await this.list()).filter((m) => m.name === nameOrId).map((m) => m.id);
      if (!ids.length) throw new AbenixError(404, `No ML model called ${nameOrId}.`, 'NOT_FOUND');
    } else {
      ids = [await this.id(nameOrId)];
    }
    for (const mid of ids) await platformCall(this.client, 'DELETE', `/api/ml-models/${mid}`);
    for (const [n, i] of [...this.ids]) if (ids.includes(i)) this.ids.delete(n);
    return { deleted: ids };
  }

  /** Run the model on inputData, for example { features: [...] } or a list of rows. */
  async predict(nameOrId: string, inputData: unknown): Promise<Record<string, unknown>> {
    const mid = await this.id(nameOrId);
    return (await platformCall<Record<string, unknown>>(this.client, 'POST', `/api/ml-models/${mid}/predict`, { input_data: inputData })) || {};
  }

  /** Per-feature contributions for one row and the waterfall from baseline to prediction. The baseline defaults to the model's training means, else zeros. */
  async explain(nameOrId: string, inputData: unknown, baseline?: Record<string, number> | number[]): Promise<MLExplanation> {
    const mid = await this.id(nameOrId);
    const body: Record<string, unknown> = { input_data: inputData };
    if (baseline !== undefined) body.baseline = baseline;
    return platformCall<MLExplanation>(this.client, 'POST', `/api/ml-models/${mid}/explain`, body);
  }
}

export interface MLExplanation {
  /** linear, exact-shapley, sampled-shapley, tree-shap or linear-shap */
  method: string;
  /** what was explained, prediction, probability of a class or an anomaly score */
  target: string;
  prediction: number;
  base_value: number;
  baseline: Record<string, number>;
  /** request, training_means, training_means_from_model or zeros */
  baseline_source: string;
  feature_names: string[];
  contributions: { feature: string; value: number; baseline: number; contribution: number }[];
  waterfall: { feature: string; contribution: number; start: number; end: number }[];
  additivity_gap: number;
  [k: string]: unknown;
}

export interface CodeAsset {
  id: string;
  name: string;
  description: string | null;
  /** analyzing, ready or failed */
  status: string;
  error: string | null;
  version?: number;
  input_schema: Record<string, unknown> | null;
  output_schema: Record<string, unknown> | null;
  [k: string]: unknown;
}

export interface CodeSourceOptions {
  gitUrl?: string;
  gitRef?: string;
  /** Name for raw bytes, code.zip when left out. */
  filename?: string;
}

/** Upload code as an asset and ship new versions of it. */
export class CodeAssetsClient {
  constructor(private client: Abenix) {}

  list(): Promise<CodeAsset[]> {
    return platformCall<CodeAsset[]>(this.client, 'GET', '/api/code-assets').then((r) => r || []);
  }

  private async id(nameOrId: string): Promise<string> {
    if (UUID_RE.test(nameOrId)) return nameOrId;
    const hit = (await this.list()).find((a) => a.name === nameOrId);
    if (!hit) throw new AbenixError(404, `No code asset called ${nameOrId}.`, 'NOT_FOUND');
    return hit.id;
  }

  async get(nameOrId: string): Promise<CodeAsset> {
    return platformCall(this.client, 'GET', `/api/code-assets/${await this.id(nameOrId)}`);
  }

  private async form(meta: Record<string, unknown>, source: FileInput | undefined, opts: CodeSourceOptions): Promise<FormData> {
    if (source === undefined && !opts.gitUrl) throw new Error('Give a zip, a tar.gz, a folder or a gitUrl');
    if (opts.gitUrl) {
      meta.git_url = opts.gitUrl;
      if (opts.gitRef) meta.git_ref = opts.gitRef;
    }
    const form = new FormData();
    form.append('metadata', JSON.stringify(meta));
    if (source !== undefined) {
      const { blob, filename } = await readInput(source, { filename: opts.filename, allowFolder: true, fallbackName: 'code.zip' });
      form.append('file', blob, filename);
    }
    return form;
  }

  /** New asset from a zip, a tar.gz, a folder (Node, zipped for you) or a git URL. Check status and error on the result. */
  async create(name: string, source?: FileInput, opts: CodeSourceOptions & { description?: string } = {}): Promise<CodeAsset> {
    return platformCall(this.client, 'POST', '/api/code-assets', await this.form({ name, description: opts.description ?? '' }, source, opts));
  }

  /** Replace the code behind an asset. A version that does not analyse cleanly throws AbenixError 422 and the live one stays. */
  async newVersion(nameOrId: string, source?: FileInput, opts: CodeSourceOptions = {}): Promise<CodeAsset> {
    const assetId = await this.id(nameOrId);
    return platformCall(this.client, 'POST', `/api/code-assets/${assetId}/versions`, await this.form({}, source, opts));
  }
}

export type KillSwitchScope = 'all' | 'agent' | 'pipeline' | 'tool' | 'model' | 'trigger' | 'decision' | 'source' | 'improvements';

export interface KillSwitch {
  id: string;
  scope: KillSwitchScope;
  target: string;
  reason: string;
  active: boolean;
  set_by: string | null;
  set_at: string | null;
  cleared_by: string | null;
  cleared_at: string | null;
}

/** Stop agents, pipelines, tools, models and more across the tenant at once. */
export class KillSwitchesClient {
  constructor(private client: Abenix) {}

  async list(opts: { includeCleared?: boolean } = {}): Promise<KillSwitch[]> {
    const data = await platformCall<{ switches: KillSwitch[] }>(this.client, 'GET', `/api/governance/kill-switches${opts.includeCleared ? '?include_cleared=true' : ''}`);
    return data?.switches || [];
  }

  /** target is a name or id within the scope, * for all of them. A switch already on comes back as it is. */
  set(scope: KillSwitchScope, target: string, reason: string): Promise<KillSwitch> {
    return platformCall(this.client, 'POST', '/api/governance/kill-switches', { scope, target: target || '*', reason });
  }

  clear(switchId: string): Promise<KillSwitch> {
    return platformCall(this.client, 'POST', `/api/governance/kill-switches/${switchId}/clear`);
  }
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  scopes: Record<string, unknown> | null;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string | null;
  /** Only on create. */
  raw_key?: string;
  [k: string]: unknown;
}

/** API keys of the calling user, or of the whole tenant for an admin. */
/** Members of the workspace and who of them can approve decisions. */
export class TeamClient {
  constructor(private client: Abenix) {}

  async members(): Promise<any[]> {
    const r: any = await platformCall<any>(this.client, 'GET', '/api/team/members');
    return r?.members || [];
  }

  /** Add someone to Decision reviewers or take them out. warning says when few people are left who can approve. */
  setApprover(userId: string, canApproveDecisions: boolean): Promise<any> {
    return platformCall(this.client, 'PUT', `/api/team/${encodeURIComponent(userId)}/approver`, { can_approve_decisions: canApproveDecisions });
  }
}

export class ApiKeysClient {
  constructor(private client: Abenix) {}

  list(): Promise<ApiKey[]> {
    return platformCall<ApiKey[]>(this.client, 'GET', '/api/api-keys').then((r) => r || []);
  }

  /** raw_key is only in this response. scopes is { can_delegate }, { allowed_actions } or a list of actions. */
  create(name: string, scopes?: Record<string, unknown> | string[], opts: { expiresAt?: string; maxMonthlyTokens?: number; maxMonthlyCost?: number } = {}): Promise<ApiKey> {
    const shaped = Array.isArray(scopes) ? { allowed_actions: scopes } : scopes;
    if (shaped && !('can_delegate' in shaped) && !('allowed_actions' in shaped)) {
      return Promise.reject(new Error('scopes takes can_delegate or allowed_actions'));
    }
    const body: Record<string, unknown> = { name, scopes: shaped ?? null };
    if (opts.expiresAt !== undefined) body.expires_at = opts.expiresAt;
    if (opts.maxMonthlyTokens !== undefined) body.max_monthly_tokens = opts.maxMonthlyTokens;
    if (opts.maxMonthlyCost !== undefined) body.max_monthly_cost = opts.maxMonthlyCost;
    return platformCall(this.client, 'POST', '/api/api-keys', body);
  }

  revoke(keyId: string): Promise<{ id: string; status: string }> {
    return platformCall(this.client, 'DELETE', `/api/api-keys/${keyId}`);
  }
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

export type ProposalState =
  | 'drafting' | 'proving' | 'failed_proof' | 'awaiting_approval' | 'approved'
  | 'rejected' | 'released' | 'kept' | 'rolled_back' | 'superseded';

export interface ProposalRow {
  id: string;
  agent: { id: string; name: string };
  cluster: { id: string | null; title: string };
  change_kind: string;
  change_label: string;
  diff: Record<string, unknown>;
  rationale: string;
  risk: 'low' | 'medium' | 'high';
  state: ProposalState;
  state_label: string;
  progress: Record<string, unknown>;
  proof: Record<string, unknown>;
  approval_id: string | null;
  released_revision_id: string | null;
  watch_until: string | null;
  watch_result: Record<string, unknown> | null;
  created_at: string | null;
}

/** Fixes proposed from an agent's lessons, their proof, approval and watch. */
export class ImprovementsClient {
  constructor(private client: Abenix) {}

  /** Proposals you may see, newest first. */
  async list(opts: { agentId?: string; state?: ProposalState; limit?: number } = {}): Promise<ProposalRow[]> {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 50) });
    if (opts.agentId) q.set('agent_id', opts.agentId);
    if (opts.state) q.set('state', opts.state);
    const out = await platformCall<{ items: ProposalRow[] }>(this.client, 'GET', `/api/improvements/proposals?${q.toString()}`);
    return out?.items ?? [];
  }

  /** One proposal with its diff, proof, progress and watch result. */
  get(proposalId: string): Promise<ProposalRow> {
    return platformCall(this.client, 'GET', `/api/improvements/proposals/${proposalId}`);
  }
}

/** Tell an agent what it got wrong. Lessons feed proposals, they never change an agent on their own. */
export class LessonsClient {
  constructor(private client: Abenix) {}

  report(
    agentId: string,
    note: string,
    opts: { expected?: string; executionId?: string; input?: string; output?: string } = {},
  ): Promise<any> {
    if (!note.trim()) return Promise.reject(new Error('Say what was wrong.'));
    const body: Record<string, unknown> = { agent_id: agentId, note, source: 'sdk' };
    if (opts.expected !== undefined) body.expected = opts.expected;
    if (opts.input !== undefined) body.input = opts.input;
    if (opts.output !== undefined) body.output = opts.output;
    if (opts.executionId) body.execution_id = opts.executionId;
    return platformCall(this.client, 'POST', '/api/improvements/lessons', body);
  }
}

/** Thumbs up or down on an answer, with an optional correction. */
export class FeedbackClient {
  constructor(private client: Abenix) {}

  /** rating is 1 or -1. A thumbs down with a correction becomes a lesson with that as the right answer. */
  give(
    rating: 1 | -1,
    opts: { executionId?: string; conversationId?: string; messageId?: string; agentId?: string; correction?: string } = {},
  ): Promise<{ id: string; lesson_id?: string | null }> {
    if (rating !== 1 && rating !== -1) return Promise.reject(new Error('rating is 1 or -1.'));
    const body: Record<string, unknown> = { rating };
    if (opts.executionId) body.execution_id = opts.executionId;
    if (opts.conversationId) body.conversation_id = opts.conversationId;
    if (opts.messageId) body.message_id = opts.messageId;
    if (opts.agentId) body.agent_id = opts.agentId;
    if (opts.correction !== undefined) body.correction = opts.correction;
    return platformCall(this.client, 'POST', '/api/improvements/feedback', body);
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
      selfApproved: !!raw.self_approved,
      eligibleApproverCount: (raw.eligible_approver_count as number | null | undefined) ?? null,
      soleOperatorAvailable: !!raw.sole_operator_available,
      canSign: !!raw.can_sign,
      cannotSignReason: (raw.cannot_sign_reason as string | null | undefined) ?? null,
      summary: (raw.summary as string | undefined) ?? '',
      kindLabel: (raw.kind_label as string | undefined) ?? '',
      withdrawReason: (raw.withdraw_reason as string | null | undefined) ?? null,
      withdrawnByName: (raw.withdrawn_by_name as string | null | undefined) ?? null,
    };
  }

  async list(opts?: {
    status?: 'pending' | 'approved' | 'denied' | 'expired' | 'returned' | 'withdrawn';
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

  /** Settled approvals you asked for, signed or could have signed, a page at a time. */
  async resolved(opts: { offset?: number; limit?: number } = {}): Promise<{ items: Approval[]; total: number; hasMore: boolean }> {
    const params = new URLSearchParams({ status: 'resolved', offset: String(opts.offset ?? 0), limit: String(opts.limit ?? 50) });
    const res = await this.client._fetch(`/api/approvals?${params.toString()}`);
    if (!res.ok) throw new Error(`Failed to list approvals: HTTP ${res.status}`);
    const data = await res.json();
    return {
      items: (data.data || []).map((row: Record<string, unknown>) => this._normalize(row)),
      total: data.meta?.total ?? 0,
      hasMore: !!data.meta?.has_more,
    };
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
    options?: { reason?: string; clientToken?: string; editedArguments?: Record<string, unknown>; soleOperator?: boolean },
  ): Promise<Approval> {
    const body: Record<string, unknown> = {
      decision,
      reason: options?.reason || '',
    };
    // signing your own request alone, only when nobody else in the workspace can
    if (options?.soleOperator) {
      if ((options.reason || '').trim().length < 10) {
        return Promise.reject(new Error('A sole-operator sign-off needs a reason of at least 10 characters.'));
      }
      body.sole_operator = true;
    }
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

  /** A reason of at least 5 characters is required, the requester is told it. */
  deny(approvalId: string, options?: { reason?: string; clientToken?: string }): Promise<Approval> {
    if ((options?.reason || '').trim().length < 5) {
      return Promise.reject(new Error('Say why you are denying it, at least 5 characters. The requester is told.'));
    }
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
    // a busy server (429, 503) or a dropped connection is retried until the timeout
    const deadline = Date.now() + Math.max(1, options?.timeoutSeconds ?? 60) * 1000;
    const pollMs = Math.max(0, (options?.pollSeconds ?? 2) * 1000);
    const pause = (ms: number) =>
      new Promise((r) => setTimeout(r, Math.max(0, Math.min(ms, deadline - Date.now()))));
    let last: Approval | null = null;
    while (Date.now() < deadline) {
      const chunk = Math.max(1, Math.min(120, Math.floor((deadline - Date.now()) / 1000)));
      let res: Response;
      try {
        res = await this.client._fetch(
          `/api/approvals/${approvalId}/wait?timeout_seconds=${chunk}`,
          { signal: AbortSignal.timeout((chunk + 30) * 1000) },
        );
      } catch {
        await pause(2000);
        continue;
      }
      if ([429, 502, 503, 504].includes(res.status)) {
        await pause((Number(res.headers.get('Retry-After')) || 2) * 1000);
        continue;
      }
      if (!res.ok) throw new Error(`Wait failed: HTTP ${res.status}`);
      const data = await res.json();
      last = this._normalize(data.data || {});
      if (last.status !== 'pending') return last;
      if (pollMs > 0) await pause(pollMs);
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
