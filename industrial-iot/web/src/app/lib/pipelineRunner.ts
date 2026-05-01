
export interface PipelineRunResult {
  ok: boolean;
  final_output?: Record<string, unknown>;
  node_results?: Record<string, {
    node_id: string;
    status: string;
    tool_name?: string;
    duration_ms?: number;
    error?: string | null;
    output?: unknown;
  }>;
  execution_id?: string;
  status?: string;
  error?: string;
  input_tokens?: number;
  output_tokens?: number;
  cost?: number;
  duration_ms?: number;
}

export type PipelineKey = 'pump' | 'cold-chain';

const SLUG_TO_KEY: Record<string, PipelineKey> = {
  'pump': 'pump',
  'iot-pump-pipeline': 'pump',
  'cold-chain': 'cold-chain',
  'iot-coldchain-pipeline': 'cold-chain',
};

export async function findPipelineBySlug(slug: string): Promise<PipelineKey | null> {
  const key = SLUG_TO_KEY[slug];
  if (!key) return null;
  const available = await listPipelines();
  return available.some((p) => p.key === key) ? key : null;
}

/**
 * Execute one of the showcase pipelines synchronously.
 *
 * @param pipelineKey  short key the API catalog exposes (not an Abenix UUID).
 * @param message      text or JSON payload the pipeline takes as input.
 * @param context      optional pipeline context (policy, thresholds, etc.).
 */
export async function runPipeline(
  pipelineKey: PipelineKey,
  message: string | object,
  context: Record<string, unknown>,
  // waitSeconds accepted for source compatibility with the pre-split
  // API — the timeout now lives on the standalone's FastAPI side.
  opts: { signal?: AbortSignal; waitSeconds?: number } = {},
): Promise<PipelineRunResult> {
  let res: Response;
  try {
    res = await fetch(`/api/industrial-iot/pipelines/${pipelineKey}/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, context }),
      signal: opts.signal,
    });
  } catch (e) {
    return { ok: false, error: (e as Error).message || 'network error' };
  }

  let body: any = {};
  try { body = await res.json(); } catch { /* ignore */ }

  if (!res.ok || body?.ok === false) {
    return {
      ok: false,
      error: body?.error || `HTTP ${res.status}`,
    };
  }

  return {
    ok: true,
    status: body.status,
    final_output: body.final_output,
    node_results: body.node_results,
    execution_id: body.execution_id,
    input_tokens: body.input_tokens,
    output_tokens: body.output_tokens,
    cost: body.cost,
    duration_ms: body.duration_ms,
  };
}

/**
 * List the pipelines the API currently exposes. Mostly for UI tile
 * rendering on first load; the deep content is per-tab.
 */
export async function listPipelines(): Promise<Array<{ key: string; label: string; description: string }>> {
  const r = await fetch('/api/industrial-iot/pipelines');
  if (!r.ok) return [];
  const body = await r.json();
  return body?.data || [];
}
