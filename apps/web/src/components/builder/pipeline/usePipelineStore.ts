// usePipelineStore.ts — Zustand store for pipeline builder state.
// Follows the same create<State>((set, get) => ...) pattern used by the
// chatStore and notificationStore in this codebase.

import { create } from 'zustand';
import {
  type PipelineStep,
  type PipelineEdgeConfig,
  type PipelineConfig,
  isValidConnection,
  serializeConfig,
  serializeForExecution,
  deserializeConfig,
} from './pipelineUtils';

// ── Constants ─────────────────────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Types ─────────────────────────────────────────────────────────────────

export type NodeStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'retrying';

export interface NodeResult {
  output: unknown;
  durationMs: number;
  error?: string;
  attempt?: number;
  forEachResults?: unknown[];
}

export interface ExecutionState {
  isRunning: boolean;
  executionId: string | null;
  nodeStatuses: Record<string, NodeStatus>;
  nodeResults: Record<string, NodeResult>;
  executionPath: string[];
  totalDurationMs: number;
}

export interface ValidationError {
  node_id: string;
  field: string;
  message: string;
  severity: 'error' | 'warning';
  suggestion: string;
}

export interface ValidationState {
  errors: ValidationError[];
  warnings: ValidationError[];
  isValidating: boolean;
  lastValidatedAt: number;
}

interface PipelineStore {
  // ── State ──────────────────────────────────────────────────────────────
  steps: PipelineStep[];
  edges: PipelineEdgeConfig[];
  execution: ExecutionState;
  validation: ValidationState;
  agentTools: string[];
  /**
   * Extra context keys the agent promises it'll have at runtime — the
   * names declared under `input_variables`. Without these, the backend
   * validator warns on `{{context.custom_var}}` as unknown.
   */
  agentContextKeys: string[];
  selectedStepId: string | null;
  dirty: boolean;

  // ── Agent tools ────────────────────────────────────────────────────────
  setAgentTools: (tools: string[]) => void;
  setAgentContextKeys: (keys: string[]) => void;

  // ── Step CRUD ──────────────────────────────────────────────────────────
  addStep: (
    toolName: string,
    label: string,
    position: { x: number; y: number },
  ) => string;
  removeStep: (id: string) => void;
  updateStep: (id: string, updates: Partial<PipelineStep>) => void;

  // ── Edge CRUD ──────────────────────────────────────────────────────────
  connectSteps: (
    sourceId: string,
    targetId: string,
    sourceField?: string,
  ) => string | null;
  disconnectSteps: (edgeId: string) => void;

  // ── Selection ──────────────────────────────────────────────────────────
  setSelectedStep: (id: string | null) => void;

  // ── Serialization ──────────────────────────────────────────────────────
  serialize: () => PipelineConfig;
  deserialize: (config: PipelineConfig) => void;
  reset: () => void;

  // ── Execution ──────────────────────────────────────────────────────────
  executeAndTrack: (agentId: string) => Promise<void>;
  executeWithStreaming: (agentId: string) => Promise<void>;
  resetExecution: () => void;

  // ── Validation ─────────────────────────────────────────────────────────
  validate: (agentTools: string[], contextKeys?: string[]) => Promise<void>;
  validateDebounced: (agentTools: string[], contextKeys?: string[]) => void;
  getStepErrors: (stepId: string) => ValidationError[];
}

// ── Helpers ───────────────────────────────────────────────────────────────

function generateStepId(): string {
  return `step_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
}

function generateEdgeId(): string {
  return `edge_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
}

function getToken(): string {
  return typeof window !== 'undefined'
    ? localStorage.getItem('access_token') || ''
    : '';
}

const INITIAL_EXECUTION: ExecutionState = {
  isRunning: false,
  executionId: null,
  nodeStatuses: {},
  nodeResults: {},
  executionPath: [],
  totalDurationMs: 0,
};

const INITIAL_VALIDATION: ValidationState = {
  errors: [],
  warnings: [],
  isValidating: false,
  lastValidatedAt: 0,
};

// Debounce timer for validateDebounced (module-scoped so it survives
// repeated store calls without tracking it in state).
let _validationDebounceTimer: ReturnType<typeof setTimeout> | null = null;

// ── Store ─────────────────────────────────────────────────────────────────

export const usePipelineStore = create<PipelineStore>((set, get) => ({
  // ── Initial state ──────────────────────────────────────────────────────
  steps: [],
  edges: [],
  execution: { ...INITIAL_EXECUTION },
  validation: { ...INITIAL_VALIDATION },
  agentTools: [],
  agentContextKeys: [],
  selectedStepId: null,
  dirty: false,

  setAgentTools: (tools: string[]): void => {
    set({ agentTools: tools });
    if (get().steps.length > 0) {
      get().validateDebounced(tools, get().agentContextKeys);
    }
  },

  setAgentContextKeys: (keys: string[]): void => {
    set({ agentContextKeys: keys });
    if (get().steps.length > 0) {
      get().validateDebounced(get().agentTools, keys);
    }
  },

  // ── Step CRUD ──────────────────────────────────────────────────────────

  addStep: (
    toolName: string,
    label: string,
    position: { x: number; y: number },
  ): string => {
    const id = generateStepId();

    const newStep: PipelineStep = {
      id,
      toolName,
      label,
      arguments: {},
      dependsOn: [],
      condition: null,
      inputMappings: {},
      position: { ...position },
      maxRetries: 0,
      retryDelayMs: 1000,
      forEach: null,
      timeoutSeconds: null,
      onError: 'stop',
      errorBranchNode: null,
      switchConfig: null,
      mergeConfig: null,
    };

    set((state) => ({
      steps: [...state.steps, newStep],
      dirty: true,
    }));

    // Trigger backend validation (debounced)
    const { agentTools, validateDebounced } = get();
    validateDebounced(agentTools);

    return id;
  },

  removeStep: (id: string): void => {
    set((state) => {
      // Remove edges that reference this step
      const remainingEdges = state.edges.filter(
        (e) => e.source !== id && e.target !== id,
      );

      // Remove step and clean up dependsOn in remaining steps
      const remainingSteps = state.steps
        .filter((s) => s.id !== id)
        .map((s) => ({
          ...s,
          dependsOn: s.dependsOn.filter((dep) => dep !== id),
          // Also clean up inputMappings that reference the removed step
          inputMappings: Object.fromEntries(
            Object.entries(s.inputMappings).filter(
              ([, mapping]) => mapping.sourceNode !== id,
            ),
          ),
        }));

      return {
        steps: remainingSteps,
        edges: remainingEdges,
        dirty: true,
        // Deselect if the removed step was selected
        selectedStepId:
          state.selectedStepId === id ? null : state.selectedStepId,
      };
    });
    const { agentTools, validateDebounced } = get();
    validateDebounced(agentTools);
  },

  updateStep: (id: string, updates: Partial<PipelineStep>): void => {
    set((state) => ({
      steps: state.steps.map((step) =>
        step.id === id ? { ...step, ...updates } : step,
      ),
      dirty: true,
    }));
    const { agentTools, validateDebounced } = get();
    validateDebounced(agentTools);
  },

  // ── Edge CRUD ──────────────────────────────────────────────────────────

  connectSteps: (
    sourceId: string,
    targetId: string,
    sourceField?: string,
  ): string | null => {
    const { steps, edges } = get();

    // Validate the connection would not create a cycle
    if (!isValidConnection(sourceId, targetId, steps)) {
      return null;
    }

    // Prevent duplicate edges between the same source and target
    const duplicate = edges.some(
      (e) => e.source === sourceId && e.target === targetId,
    );
    if (duplicate) {
      return null;
    }

    const edgeId = generateEdgeId();

    const newEdge: PipelineEdgeConfig = {
      id: edgeId,
      source: sourceId,
      target: targetId,
    };
    if (sourceField) {
      newEdge.sourceField = sourceField;
    }

    set((state) => ({
      edges: [...state.edges, newEdge],
      steps: state.steps.map((step) =>
        step.id === targetId && !step.dependsOn.includes(sourceId)
          ? { ...step, dependsOn: [...step.dependsOn, sourceId] }
          : step,
      ),
      dirty: true,
    }));

    // Auto-populate template variable reference in downstream node
    // If the downstream node has an empty input_message/prompt/query, suggest the upstream output
    const updatedSteps = get().steps;
    const targetStep = updatedSteps.find((s) => s.id === targetId);
    if (targetStep) {
      const upstreamRef = `{{${sourceId}.response}}`;
      const args = targetStep.arguments || {};
      if (args.input_message !== undefined && !args.input_message) {
        set((state) => ({
          steps: state.steps.map((s) =>
            s.id === targetId
              ? { ...s, arguments: { ...s.arguments, input_message: upstreamRef } }
              : s,
          ),
        }));
      } else if (args.prompt !== undefined && !args.prompt) {
        set((state) => ({
          steps: state.steps.map((s) =>
            s.id === targetId
              ? { ...s, arguments: { ...s.arguments, prompt: upstreamRef } }
              : s,
          ),
        }));
      } else if (args.query !== undefined && !args.query) {
        set((state) => ({
          steps: state.steps.map((s) =>
            s.id === targetId
              ? { ...s, arguments: { ...s.arguments, query: upstreamRef } }
              : s,
          ),
        }));
      }
    }

    const { agentTools, validateDebounced } = get();
    validateDebounced(agentTools);

    return edgeId;
  },

  disconnectSteps: (edgeId: string): void => {
    const { edges } = get();
    const edge = edges.find((e) => e.id === edgeId);
    if (!edge) return;

    const { source: sourceId, target: targetId } = edge;

    set((state) => ({
      edges: state.edges.filter((e) => e.id !== edgeId),
      steps: state.steps.map((step) =>
        step.id === targetId
          ? {
              ...step,
              dependsOn: step.dependsOn.filter((dep) => dep !== sourceId),
            }
          : step,
      ),
      dirty: true,
    }));
    const { agentTools, validateDebounced } = get();
    validateDebounced(agentTools);
  },

  // ── Selection ──────────────────────────────────────────────────────────

  setSelectedStep: (id: string | null): void => {
    set({ selectedStepId: id });
  },

  // ── Serialization ──────────────────────────────────────────────────────

  serialize: (): PipelineConfig => {
    const { steps, edges } = get();
    // Use a default viewport — the actual viewport is managed by React Flow
    // and can be provided via an override if needed.
    return serializeConfig(steps, edges, { x: 0, y: 0, zoom: 1 });
  },

  deserialize: (config: PipelineConfig): void => {
    const { steps, edges } = deserializeConfig(config);
    set({
      steps,
      edges,
      dirty: false,
      selectedStepId: null,
      execution: { ...INITIAL_EXECUTION },
    });
  },

  reset: (): void => {
    set({
      steps: [],
      edges: [],
      execution: { ...INITIAL_EXECUTION },
      selectedStepId: null,
      dirty: false,
    });
  },

  // ── Execution ──────────────────────────────────────────────────────────

  executeAndTrack: async (agentId: string): Promise<void> => {
    const { steps } = get();

    // 1. Mark all nodes as pending and set running flag
    const initialStatuses: Record<string, NodeStatus> = {};
    for (const step of steps) {
      initialStatuses[step.id] = 'pending';
    }

    set({
      execution: {
        isRunning: true,
        executionId: null,
        nodeStatuses: initialStatuses,
        nodeResults: {},
        executionPath: [],
        totalDurationMs: 0,
      },
    });

    // 2. Call the execute API
    try {
      const token = getToken();
      const serializedNodes = serializeForExecution(steps);

      const response = await fetch(
        `${API_URL}/api/pipelines/${agentId}/execute`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ nodes: serializedNodes }),
        },
      );

      if (!response.ok) {
        const errorBody = await response.json().catch(() => null);
        const errorMessage =
          errorBody?.error?.message ||
          errorBody?.error ||
          `Execution failed with status ${response.status}`;

        // Mark all pending nodes as failed
        set((state) => {
          const failedStatuses: Record<string, NodeStatus> = {};
          for (const [nodeId, status] of Object.entries(
            state.execution.nodeStatuses,
          )) {
            failedStatuses[nodeId] = status === 'pending' ? 'failed' : status;
          }
          return {
            execution: {
              ...state.execution,
              isRunning: false,
              nodeStatuses: failedStatuses,
              nodeResults: {
                _error: {
                  output: null,
                  durationMs: 0,
                  error: errorMessage,
                },
              },
            },
          };
        });
        return;
      }

      const json = await response.json();
      const data = json.data;

      // 3. Map response to execution state
      const nodeStatuses: Record<string, NodeStatus> = {};
      const nodeResults: Record<string, NodeResult> = {};
      const executionPath: string[] = [];

      if (data?.node_results) {
        for (const [nodeId, result] of Object.entries(
          data.node_results as Record<
            string,
            {
              status: string;
              output: unknown;
              duration_ms: number;
              error?: string;
            }
          >,
        )) {
          // Map backend status strings to our NodeStatus type
          const statusMap: Record<string, NodeStatus> = {
            completed: 'completed',
            failed: 'failed',
            skipped: 'skipped',
            running: 'running',
            pending: 'pending',
          };
          nodeStatuses[nodeId] =
            statusMap[result.status] || 'completed';

          nodeResults[nodeId] = {
            output: result.output,
            durationMs: result.duration_ms ?? 0,
            ...(result.error ? { error: result.error } : {}),
          };

          // Build execution path from completed/failed nodes
          if (
            result.status === 'completed' ||
            result.status === 'failed'
          ) {
            executionPath.push(nodeId);
          }
        }
      }

      // Fill in statuses for any steps not present in the response
      for (const step of steps) {
        if (!(step.id in nodeStatuses)) {
          nodeStatuses[step.id] = 'skipped';
        }
      }

      set({
        execution: {
          isRunning: false,
          executionId: data?.execution_id ?? null,
          nodeStatuses,
          nodeResults,
          executionPath,
          totalDurationMs: data?.total_duration_ms ?? 0,
        },
      });
    } catch (err) {
      // Network or parsing error — mark everything as failed
      const errorMessage =
        err instanceof Error ? err.message : 'Unknown execution error';

      set((state) => {
        const failedStatuses: Record<string, NodeStatus> = {};
        for (const nodeId of Object.keys(state.execution.nodeStatuses)) {
          failedStatuses[nodeId] = 'failed';
        }
        return {
          execution: {
            ...state.execution,
            isRunning: false,
            nodeStatuses: failedStatuses,
            nodeResults: {
              _error: {
                output: null,
                durationMs: 0,
                error: errorMessage,
              },
            },
          },
        };
      });
    }
  },

  executeWithStreaming: async (agentId: string): Promise<void> => {
    const { steps } = get();

    const initialStatuses: Record<string, NodeStatus> = {};
    for (const step of steps) {
      initialStatuses[step.id] = 'pending';
    }

    set({
      execution: {
        isRunning: true,
        executionId: null,
        nodeStatuses: initialStatuses,
        nodeResults: {},
        executionPath: [],
        totalDurationMs: 0,
      },
    });

    try {
      const token = getToken();
      const serializedNodes = serializeForExecution(steps);

      const response = await fetch(
        `${API_URL}/api/pipelines/${agentId}/execute-stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ nodes: serializedNodes }),
        },
      );

      if (!response.ok || !response.body) {
        const errorBody = await response.json().catch(() => null);
        const errorMessage =
          errorBody?.error?.message || `Execution failed with status ${response.status}`;

        set((state) => {
          const failedStatuses: Record<string, NodeStatus> = {};
          for (const nodeId of Object.keys(state.execution.nodeStatuses)) {
            failedStatuses[nodeId] = 'failed';
          }
          return {
            execution: {
              ...state.execution,
              isRunning: false,
              nodeStatuses: failedStatuses,
              nodeResults: { _error: { output: null, durationMs: 0, error: errorMessage } },
            },
          };
        });
        return;
      }

      // SSE streaming
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let eventType = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));

            if (eventType === 'node_start') {
              set((state) => ({
                execution: {
                  ...state.execution,
                  nodeStatuses: {
                    ...state.execution.nodeStatuses,
                    [data.node_id]: 'running',
                  },
                },
              }));
            } else if (eventType === 'node_complete') {
              set((state) => ({
                execution: {
                  ...state.execution,
                  nodeStatuses: {
                    ...state.execution.nodeStatuses,
                    [data.node_id]: data.status === 'completed' ? 'completed' : 'failed',
                  },
                  nodeResults: {
                    ...state.execution.nodeResults,
                    [data.node_id]: {
                      output: data.output,
                      durationMs: data.duration_ms ?? 0,
                      ...(data.error ? { error: data.error } : {}),
                    },
                  },
                  executionPath: [...state.execution.executionPath, data.node_id],
                },
              }));
            } else if (eventType === 'pipeline_complete') {
              set({
                execution: {
                  isRunning: false,
                  executionId: data.execution_id ?? null,
                  nodeStatuses: get().execution.nodeStatuses,
                  nodeResults: get().execution.nodeResults,
                  executionPath: get().execution.executionPath,
                  totalDurationMs: data.total_duration_ms ?? 0,
                },
              });
            } else if (eventType === 'pipeline_error') {
              set((state) => ({
                execution: {
                  ...state.execution,
                  isRunning: false,
                  nodeResults: {
                    ...state.execution.nodeResults,
                    _error: { output: null, durationMs: 0, error: data.error },
                  },
                },
              }));
            }
            eventType = '';
          }
        }
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown execution error';
      set((state) => {
        const failedStatuses: Record<string, NodeStatus> = {};
        for (const nodeId of Object.keys(state.execution.nodeStatuses)) {
          failedStatuses[nodeId] = 'failed';
        }
        return {
          execution: {
            ...state.execution,
            isRunning: false,
            nodeStatuses: failedStatuses,
            nodeResults: { _error: { output: null, durationMs: 0, error: errorMessage } },
          },
        };
      });
    }
  },

  resetExecution: (): void => {
    set({ execution: { ...INITIAL_EXECUTION } });
  },

  // ── Validation ─────────────────────────────────────────────────────────

  validate: async (agentTools: string[], contextKeys?: string[]): Promise<void> => {
    const { steps } = get();
    if (steps.length === 0) {
      set({
        validation: {
          errors: [],
          warnings: [],
          isValidating: false,
          lastValidatedAt: Date.now(),
        },
      });
      return;
    }

    set((state) => ({
      validation: { ...state.validation, isValidating: true },
    }));

    try {
      // Use the same serialization as execution so the validator sees the
      // exact payload the backend pipeline executor will receive.
      const nodes = serializeForExecution(steps);

      const resp = await fetch(`${API_URL}/api/pipelines/validate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({
          nodes,
          tools: agentTools,
          // Agent-declared input_variables are runtime context keys;
          // the validator will treat `{{context.<name>}}` as known when
          // <name> appears in this list. Falls back to the store's
          // cached list if the caller didn't pass anything.
          context_keys: contextKeys ?? get().agentContextKeys,
        }),
      });

      if (!resp.ok) {
        set((state) => ({
          validation: { ...state.validation, isValidating: false },
        }));
        return;
      }

      const body = (await resp.json()) as {
        data?: {
          valid: boolean;
          errors: ValidationError[];
          warnings: ValidationError[];
        };
      };

      const data = body.data;
      if (!data) {
        set((state) => ({
          validation: { ...state.validation, isValidating: false },
        }));
        return;
      }

      set({
        validation: {
          errors: data.errors || [],
          warnings: data.warnings || [],
          isValidating: false,
          lastValidatedAt: Date.now(),
        },
      });
    } catch (err) {
      // Silent failure — keep previous validation results and stop loading
      set((state) => ({
        validation: { ...state.validation, isValidating: false },
      }));
    }
  },

  validateDebounced: (agentTools: string[], contextKeys?: string[]): void => {
    if (_validationDebounceTimer) {
      clearTimeout(_validationDebounceTimer);
    }
    _validationDebounceTimer = setTimeout(() => {
      void get().validate(agentTools, contextKeys);
    }, 800);
  },

  getStepErrors: (stepId: string): ValidationError[] => {
    const { validation } = get();
    return [
      ...validation.errors.filter((e) => e.node_id === stepId),
      ...validation.warnings.filter((w) => w.node_id === stepId),
    ];
  },
}));
