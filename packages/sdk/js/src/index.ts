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
}

export interface Approval {
  id: string;
  agentId: string | null;
  agentExecutionId: string | null;
  title: string;
  payload: Record<string, unknown>;
  requiredSignoffs: number;
  signoffs: Array<Record<string, unknown>>;
  status: 'pending' | 'approved' | 'denied' | 'expired';
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

  constructor(config: AbenixConfig) {
    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl || 'http://localhost:8000').replace(/\/$/, '');
    this.timeout = config.timeout || 120000;
    this.defaultActAs = config.actAs;
    this.executions = new ExecutionsClient(this);
    this.agents = new AgentsClient(this);
    this.knowledge = new KnowledgeClient(this);
    this.approvals = new ApprovalsClient(this);
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

  async signoff(
    approvalId: string,
    decision: 'approve' | 'deny',
    options?: { reason?: string; clientToken?: string },
  ): Promise<Approval> {
    const body: Record<string, unknown> = {
      decision,
      reason: options?.reason || '',
    };
    if (options?.clientToken) body.client_token = options.clientToken;
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

  approve(approvalId: string, options?: { reason?: string; clientToken?: string }): Promise<Approval> {
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
