export const API_VERSION = 'v1';

export const AGENT_MODELS = [
  'claude-sonnet-4-20250514',
  'claude-haiku-4-20250514',
  'gpt-4o',
  'gpt-4o-mini',
] as const;

export type AgentModel = (typeof AGENT_MODELS)[number];

export const MAX_AGENT_ITERATIONS = 25;
export const DEFAULT_TEMPERATURE = 0.7;

export const SESSION_STATUS = {
  ACTIVE: 'active',
  COMPLETED: 'completed',
  FAILED: 'failed',
} as const;
