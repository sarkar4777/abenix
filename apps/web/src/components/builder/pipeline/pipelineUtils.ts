// pipelineUtils.ts — DAG validation and serialization utilities for the
// Abenix pipeline builder. Mirrors the backend _topological_sort and
// pipeline schema so that the frontend and API stay in lock-step.

// ── Types ──────────────────────────────────────────────────────────────────

export interface SwitchCase {
  operator: string;
  value: unknown;
  targetNode: string;
}

export interface SwitchConfig {
  sourceNode: string;
  field: string;
  cases: SwitchCase[];
  defaultNode: string | null;
}

export interface MergeConfig {
  mode: 'append' | 'zip' | 'join';
  joinField: string | null;
  sourceNodes: string[];
}

export interface PipelineStep {
  id: string;
  toolName: string;
  label: string;
  arguments: Record<string, unknown>;
  dependsOn: string[];
  condition: PipelineCondition | null;
  inputMappings: Record<string, { sourceNode: string; sourceField: string }>;
  position: { x: number; y: number };
  maxRetries: number;
  retryDelayMs: number;
  forEach: ForEachConfig | null;
  timeoutSeconds: number | null;
  onError: 'stop' | 'continue' | 'error_branch';
  errorBranchNode: string | null;
  switchConfig: SwitchConfig | null;
  mergeConfig: MergeConfig | null;
  // Engine DSL passthrough. Stored when set; UI surfaces them on the
  // step config panel so authors can match the expressiveness of the
  // YAML seed format.
  requiredIf?: string;       // template expression; node skipped when false-y
  agentSlug?: string;        // for agent_step nodes, reference a seeded agent by slug
}

export interface ForEachConfig {
  sourceNode: string;
  sourceField: string;
  itemVariable: string;
  maxConcurrency: number;
}

export interface PipelineCondition {
  sourceNode: string;
  field: string;
  operator:
    | 'eq'
    | 'neq'
    | 'gt'
    | 'lt'
    | 'gte'
    | 'lte'
    | 'contains'
    | 'not_contains'
    | 'in'
    | 'not_in';
  value: unknown;
}

export interface PipelineEdgeConfig {
  id: string;
  source: string;
  target: string;
  sourceField?: string;
  label?: string;
}

export interface PipelineConfig {
  nodes: PipelineNodeConfig[];
  edges: PipelineEdgeConfig[];
  viewport: { x: number; y: number; zoom: number };
}

export interface PipelineNodeConfig {
  id: string;
  tool_name: string;
  label: string;
  arguments: Record<string, unknown>;
  depends_on: string[];
  condition: {
    source_node: string;
    field: string;
    operator: string;
    value: unknown;
  } | null;
  input_mappings: Record<
    string,
    { source_node: string; source_field: string }
  >;
  max_retries: number;
  retry_delay_ms: number;
  for_each: {
    source_node: string;
    source_field: string;
    item_variable: string;
    max_concurrency: number;
  } | null;
  position: { x: number; y: number };
  // Engine DSL features (pipeline.py _resolve_templates / parse_pipeline_nodes).
  // Persisted only when set so old YAMLs keep the same serialized shape.
  required_if?: string | null;   // "{{expr}}" — node skipped when the resolved value is falsy
  agent_slug?: string | null;    // when tool_name=agent_step, look up system_prompt/model/tools from this seeded agent at exec time
  type?: string;                 // "agent" | "tool" | "structured" — DSL type hint consumed by the server parser
}

export interface PipelineNodeSchema {
  id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
  depends_on: string[];
  condition?: {
    source_node: string;
    field: string;
    operator: string;
    value: unknown;
  };
  input_mappings?: Record<
    string,
    { source_node: string; source_field: string }
  >;
  max_retries?: number;
  retry_delay_ms?: number;
  for_each?: {
    source_node: string;
    source_field: string;
    item_variable: string;
    max_concurrency: number;
  };
  timeout_seconds?: number;
  on_error?: string;
  error_branch_node?: string;
  switch?: {
    source_node: string;
    field: string;
    cases: { operator: string; value: unknown; target_node: string }[];
    default_node?: string | null;
  };
  merge?: {
    mode: string;
    join_field?: string | null;
    source_nodes: string[];
  };
}

// ── Cycle Detection (Kahn's Algorithm) ────────────────────────────────────

export function detectCycles(steps: PipelineStep[]): string[] {
  // Build adjacency list and in-degree map
  const inDegree = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const step of steps) {
    inDegree.set(step.id, 0);
    adjacency.set(step.id, []);
  }

  for (const step of steps) {
    for (const dep of step.dependsOn) {
      // dep -> step.id  (dep must run before step)
      const neighbours = adjacency.get(dep);
      if (neighbours) {
        neighbours.push(step.id);
      }
      inDegree.set(step.id, (inDegree.get(step.id) ?? 0) + 1);
    }
  }

  // Seed the queue with all zero-indegree nodes
  const queue: string[] = [];
  for (const [nodeId, degree] of inDegree) {
    if (degree === 0) {
      queue.push(nodeId);
    }
  }

  const processed = new Set<string>();

  while (queue.length > 0) {
    const current = queue.shift()!;
    processed.add(current);

    for (const neighbour of adjacency.get(current) ?? []) {
      const newDegree = (inDegree.get(neighbour) ?? 1) - 1;
      inDegree.set(neighbour, newDegree);
      if (newDegree === 0) {
        queue.push(neighbour);
      }
    }
  }

  // Any node that was NOT processed is part of a cycle
  const cycleNodes: string[] = [];
  for (const step of steps) {
    if (!processed.has(step.id)) {
      cycleNodes.push(step.id);
    }
  }

  return cycleNodes;
}

// ── Connection Validation ─────────────────────────────────────────────────

/**
 * Returns `true` if adding an edge from `sourceId` to `targetId` would
 * NOT create a cycle.  Intended for use as the React Flow `isValidConnection`
 * callback so users cannot draw invalid edges.
 */
export function isValidConnection(
  sourceId: string,
  targetId: string,
  steps: PipelineStep[],
): boolean {
  // Self-loops are always invalid
  if (sourceId === targetId) {
    return false;
  }

  // Both nodes must exist
  const sourceExists = steps.some((s) => s.id === sourceId);
  const targetExists = steps.some((s) => s.id === targetId);
  if (!sourceExists || !targetExists) {
    return false;
  }

  // Create a temporary copy with the prospective dependency added
  const tempSteps: PipelineStep[] = steps.map((step) => {
    if (step.id === targetId) {
      return {
        ...step,
        dependsOn: step.dependsOn.includes(sourceId)
          ? [...step.dependsOn]
          : [...step.dependsOn, sourceId],
      };
    }
    return { ...step, dependsOn: [...step.dependsOn] };
  });

  return detectCycles(tempSteps).length === 0;
}

// ── Serialization ─────────────────────────────────────────────────────────

/**
 * Strip frontend-only fields (position, label) and produce the backend
 * execution schema.  All camelCase keys are converted to snake_case.
 */
export function serializeForExecution(
  steps: PipelineStep[],
): PipelineNodeSchema[] {
  return steps.map((step) => {
    const node: PipelineNodeSchema = {
      id: step.id,
      tool_name: step.toolName,
      arguments: { ...step.arguments },
      depends_on: [...step.dependsOn],
    };

    if (step.condition) {
      node.condition = {
        source_node: step.condition.sourceNode,
        field: step.condition.field,
        operator: step.condition.operator,
        value: step.condition.value,
      };
    }

    if (Object.keys(step.inputMappings).length > 0) {
      const mappings: Record<
        string,
        { source_node: string; source_field: string }
      > = {};
      for (const [key, mapping] of Object.entries(step.inputMappings)) {
        mappings[key] = {
          source_node: mapping.sourceNode,
          source_field: mapping.sourceField,
        };
      }
      node.input_mappings = mappings;
    }

    if (step.maxRetries > 0) {
      node.max_retries = step.maxRetries;
      node.retry_delay_ms = step.retryDelayMs;
    }

    if (step.forEach) {
      node.for_each = {
        source_node: step.forEach.sourceNode,
        source_field: step.forEach.sourceField,
        item_variable: step.forEach.itemVariable,
        max_concurrency: step.forEach.maxConcurrency,
      };
    }

    if (step.timeoutSeconds) {
      node.timeout_seconds = step.timeoutSeconds;
    }

    if (step.onError !== 'stop') {
      node.on_error = step.onError;
      if (step.onError === 'error_branch' && step.errorBranchNode) {
        node.error_branch_node = step.errorBranchNode;
      }
    }

    if (step.switchConfig) {
      node.switch = {
        source_node: step.switchConfig.sourceNode,
        field: step.switchConfig.field,
        cases: step.switchConfig.cases.map(c => ({
          operator: c.operator,
          value: c.value,
          target_node: c.targetNode,
        })),
        default_node: step.switchConfig.defaultNode,
      };
    }

    if (step.mergeConfig) {
      node.merge = {
        mode: step.mergeConfig.mode,
        join_field: step.mergeConfig.joinField,
        source_nodes: step.mergeConfig.sourceNodes,
      };
    }

    // Engine DSL fields — only emitted when the author set them so
    // round-tripping a vanilla pipeline doesn't grow extra keys.
    if (step.requiredIf && step.requiredIf.trim()) {
      (node as unknown as Record<string, unknown>).required_if = step.requiredIf.trim();
    }
    if (step.agentSlug && step.agentSlug.trim()) {
      (node as unknown as Record<string, unknown>).agent_slug = step.agentSlug.trim();
      // agent_slug is only meaningful with type=agent; stamp the type
      // so parse_pipeline_nodes on the server normalises it correctly.
      (node as unknown as Record<string, unknown>).type = 'agent';
    }

    return node;
  });
}

// ── Derived Data ──────────────────────────────────────────────────────────

/**
 * Returns a sorted, deduplicated list of tool names referenced by the
 * pipeline steps.  Useful for building the tool-palette highlight list and
 * for pre-validating that all required MCP servers are connected.
 */
export function deriveToolsFromSteps(steps: PipelineStep[]): string[] {
  const tools = new Set<string>();
  for (const step of steps) {
    if (step.toolName) {
      tools.add(step.toolName);
    }
  }
  return Array.from(tools).sort();
}

// ── Validation ────────────────────────────────────────────────────────────

/**
 * Comprehensive pipeline validation.  Returns a structured result so the
 * UI can render inline errors next to the offending nodes.
 */
export function validatePipeline(
  steps: PipelineStep[],
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  // 1. At least one step
  if (steps.length === 0) {
    errors.push('Pipeline must contain at least one step.');
    return { valid: false, errors };
  }

  // 2. No duplicate IDs
  const ids = new Set<string>();
  for (const step of steps) {
    if (ids.has(step.id)) {
      errors.push(`Duplicate step ID: "${step.id}".`);
    }
    ids.add(step.id);
  }

  // 3. All dependsOn references must point to existing steps
  for (const step of steps) {
    for (const dep of step.dependsOn) {
      if (!ids.has(dep)) {
        errors.push(
          `Step "${step.id}" depends on unknown step "${dep}".`,
        );
      }
    }
  }

  // 4. No cycles
  const cycleNodes = detectCycles(steps);
  if (cycleNodes.length > 0) {
    errors.push(
      `Pipeline contains a cycle involving: ${cycleNodes.join(', ')}.`,
    );
  }

  // 5. Every step must have a toolName
  for (const step of steps) {
    if (!step.toolName || step.toolName.trim() === '') {
      errors.push(`Step "${step.id}" is missing a tool name.`);
    }
  }

  // 6. Validate for_each references
  for (const step of steps) {
    if (step.forEach) {
      if (!ids.has(step.forEach.sourceNode)) {
        errors.push(
          `Step "${step.id}" has for_each referencing unknown step "${step.forEach.sourceNode}".`,
        );
      }
      if (!step.dependsOn.includes(step.forEach.sourceNode)) {
        errors.push(
          `Step "${step.id}" has for_each source "${step.forEach.sourceNode}" but doesn't depend on it.`,
        );
      }
    }
  }

  return { valid: errors.length === 0, errors };
}

// ── Full Config Serialization (for persistence) ───────────────────────────

/**
 * Serialize the full pipeline state into the shape expected by
 * `model_config.pipeline_config`.  This includes positions, labels, edges,
 * and viewport — everything needed to restore the builder canvas.
 */
export function serializeConfig(
  steps: PipelineStep[],
  edges: PipelineEdgeConfig[],
  viewport: { x: number; y: number; zoom: number },
): PipelineConfig {
  const nodes: PipelineNodeConfig[] = steps.map((step) => ({
    id: step.id,
    tool_name: step.toolName,
    label: step.label,
    arguments: { ...step.arguments },
    depends_on: [...step.dependsOn],
    condition: step.condition
      ? {
          source_node: step.condition.sourceNode,
          field: step.condition.field,
          operator: step.condition.operator,
          value: step.condition.value,
        }
      : null,
    input_mappings: Object.fromEntries(
      Object.entries(step.inputMappings).map(([key, mapping]) => [
        key,
        { source_node: mapping.sourceNode, source_field: mapping.sourceField },
      ]),
    ),
    max_retries: step.maxRetries,
    retry_delay_ms: step.retryDelayMs,
    for_each: step.forEach
      ? {
          source_node: step.forEach.sourceNode,
          source_field: step.forEach.sourceField,
          item_variable: step.forEach.itemVariable,
          max_concurrency: step.forEach.maxConcurrency,
        }
      : null,
    position: { ...step.position },
    // Engine DSL round-trip.
    ...(step.requiredIf && step.requiredIf.trim() ? { required_if: step.requiredIf.trim() } : {}),
    ...(step.agentSlug && step.agentSlug.trim() ? { agent_slug: step.agentSlug.trim(), type: 'agent' } : {}),
  }));

  return {
    nodes,
    edges: edges.map((e) => ({ ...e })),
    viewport: { ...viewport },
  };
}

// ── Full Config Deserialization (from persistence) ────────────────────────

/**
 * Convert a persisted `PipelineConfig` back into the runtime types used by
 * the pipeline builder.  Snake_case fields are mapped back to camelCase.
 */
export function deserializeConfig(
  config: PipelineConfig,
): { steps: PipelineStep[]; edges: PipelineEdgeConfig[] } {
  // Normalise optional fields that AI-generated configs may omit
  config = {
    ...config,
    nodes: (config.nodes || []).map(n => ({ ...n, depends_on: n.depends_on || [], arguments: n.arguments || {}, input_mappings: n.input_mappings || ({} as PipelineNodeConfig['input_mappings']) })),
    edges: config.edges || [],
    viewport: config.viewport || { x: 0, y: 0, zoom: 1 },
  };

  const nodeIdSet = new Set(config.nodes.map((n) => n.id));
  const TEMPLATE_RE = /\{\{(\w+(?:\.\w+)*)\}\}/g;
  const walk = (v: unknown, out: Set<string>): void => {
    if (typeof v === 'string') {
      let m: RegExpExecArray | null;
      while ((m = TEMPLATE_RE.exec(v)) !== null) {
        const first = m[1].split('.', 1)[0];
        if (nodeIdSet.has(first)) out.add(first);
      }
    } else if (Array.isArray(v)) {
      v.forEach((x) => walk(x, out));
    } else if (v && typeof v === 'object') {
      for (const sub of Object.values(v as Record<string, unknown>)) walk(sub, out);
    }
  };
  config.nodes = config.nodes.map((n) => {
    const inferred = new Set<string>();
    walk(n.arguments, inferred);
    walk((n as unknown as Record<string, unknown>).input, inferred);
    walk((n as unknown as Record<string, unknown>).output, inferred);
    walk((n as unknown as Record<string, unknown>).context, inferred);
    walk(n.condition as unknown, inferred);
    walk(n.input_mappings as unknown, inferred);
    walk((n as unknown as Record<string, unknown>).required_if, inferred);
    inferred.delete(n.id);
    const merged = [...n.depends_on];
    for (const dep of inferred) {
      if (!merged.includes(dep)) merged.push(dep);
    }
    return merged.length === n.depends_on.length ? n : { ...n, depends_on: merged };
  });

  // Auto-generate positions if nodes don't have them (e.g., from API execution schema)
  const needsLayout = config.nodes.some(n => !n.position || (!n.position.x && !n.position.y));

  // Topological sort for auto-layout
  let positionMap: Record<string, { x: number; y: number }> = {};
  if (needsLayout) {
    const inDeg = new Map<string, number>();
    const adj = new Map<string, string[]>();
    for (const n of config.nodes) { inDeg.set(n.id, 0); adj.set(n.id, []); }
    for (const e of config.edges) {
      adj.get(e.source)?.push(e.target);
      inDeg.set(e.target, (inDeg.get(e.target) || 0) + 1);
    }
    // Also use depends_on from nodes if edges are missing
    for (const n of config.nodes) {
      for (const dep of (n.depends_on || [])) {
        if (!adj.get(dep)?.includes(n.id)) {
          adj.get(dep)?.push(n.id);
          inDeg.set(n.id, (inDeg.get(n.id) || 0) + 1);
        }
      }
    }
    const layers: string[][] = [];
    let queue = [...inDeg.entries()].filter(([, d]) => d === 0).map(([id]) => id);
    while (queue.length > 0) {
      layers.push([...queue]);
      const next: string[] = [];
      for (const id of queue) {
        for (const child of adj.get(id) || []) {
          const d = (inDeg.get(child) || 1) - 1;
          inDeg.set(child, d);
          if (d === 0) next.push(child);
        }
      }
      queue = next;
    }
    const X_GAP = 280;
    const Y_GAP = 120;
    for (let li = 0; li < layers.length; li++) {
      const layer = layers[li];
      const yStart = 100;
      for (let ni = 0; ni < layer.length; ni++) {
        positionMap[layer[ni]] = { x: 100 + li * X_GAP, y: yStart + ni * Y_GAP };
      }
    }
  }

  const steps: PipelineStep[] = config.nodes.map((node) => ({
    id: node.id,
    toolName: node.tool_name || (node as unknown as Record<string, string>).toolName || 'unknown',
    label: node.label || node.id.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
    arguments: { ...node.arguments },
    dependsOn: [...(node.depends_on || [])],
    condition: node.condition
      ? {
          sourceNode: node.condition.source_node,
          field: node.condition.field,
          operator: node.condition.operator as PipelineCondition['operator'],
          value: node.condition.value,
        }
      : null,
    inputMappings: node.input_mappings
      ? Object.fromEntries(
          Object.entries(node.input_mappings).map(([key, mapping]) => [
            key,
            { sourceNode: mapping.source_node, sourceField: mapping.source_field },
          ]),
        )
      : {},
    maxRetries: node.max_retries ?? 0,
    retryDelayMs: node.retry_delay_ms ?? 1000,
    forEach: node.for_each
      ? {
          sourceNode: node.for_each.source_node,
          sourceField: node.for_each.source_field,
          itemVariable: node.for_each.item_variable ?? 'current_item',
          maxConcurrency: node.for_each.max_concurrency ?? 10,
        }
      : null,
    timeoutSeconds: (node as unknown as Record<string, unknown>).timeout_seconds as number | null ?? null,
    onError: ((node as unknown as Record<string, unknown>).on_error as string ?? 'stop') as 'stop' | 'continue' | 'error_branch',
    errorBranchNode: (node as unknown as Record<string, unknown>).error_branch_node as string | null ?? null,
    switchConfig: null,
    mergeConfig: null,
    position: node.position?.x ? { ...node.position } : (positionMap[node.id] || { x: 100, y: 100 }),
    // Engine DSL round-trip.
    requiredIf: ((node as unknown as Record<string, unknown>).required_if as string | undefined) || undefined,
    agentSlug: ((node as unknown as Record<string, unknown>).agent_slug as string | undefined) || undefined,
  }));

  // Build edges from explicit edges array + depends_on fields
  const edgeSet = new Set<string>();
  const edges: PipelineEdgeConfig[] = [];

  // Explicit edges
  for (const e of config.edges) {
    const key = `${e.source}-${e.target}`;
    if (!edgeSet.has(key)) {
      edgeSet.add(key);
      edges.push({ ...e, id: e.id || `edge-${key}` });
    }
  }

  // Edges from depends_on (may not be in explicit edges)
  for (const node of config.nodes) {
    for (const dep of node.depends_on) {
      const key = `${dep}-${node.id}`;
      if (!edgeSet.has(key)) {
        edgeSet.add(key);
        edges.push({ id: `edge-${key}`, source: dep, target: node.id });
      }
    }
  }

  return { steps, edges };
}
