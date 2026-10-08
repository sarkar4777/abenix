export const LLM_AUTH_FOR_USERS = 'The AI model provider rejected the platform\u2019s sign-in, so these runs never reached the model. Ask an admin to reconnect the AI model.';

// rows classified before LLM_AUTH_ERROR existed still carry INFRA_AUTH_ERROR
const LLM_AUTH_SAMPLE = /oauth|access token|token has been revoked|authentication_error|api[ _-]?key/i;

export function adviceCode(g: { failure_code: string; sample_message?: string | null }): string {
  if (g.failure_code === 'INFRA_AUTH_ERROR' && LLM_AUTH_SAMPLE.test(g.sample_message || '')) return 'LLM_AUTH_ERROR';
  return g.failure_code;
}

// what people read first, the code stays as a small reference
export const FAILURE_TITLES: Record<string, string> = {
  LLM_AUTH_ERROR: 'AI provider sign-in failed',
  LLM_RATE_LIMIT: 'AI provider is limiting requests',
  LLM_PROVIDER_ERROR: 'AI provider had an error',
  LLM_INVALID_RESPONSE: 'AI reply could not be read',
  CONFIG_UNKNOWN_MODEL: 'Agent names an unknown model',
  SANDBOX_TIMEOUT: 'Code ran out of time',
  SANDBOX_NONZERO_EXIT: 'Code stopped with an error',
  SANDBOX_OOM: 'Code ran out of memory',
  SANDBOX_IMAGE_BLOCKED: 'Code image is not allowed',
  TOOL_NOT_FOUND: 'Agent called a tool that does not exist',
  TOOL_ERROR: 'A tool failed',
  BUDGET_EXCEEDED: 'Spending limit reached',
  RATE_LIMITED: 'Too many requests from one person',
  STALE_SWEEP: 'Run got stuck and was stopped',
  INFRA_CRASH: 'A platform service could not be reached',
  INFRA_AUTH_ERROR: 'A platform service refused access',
  MODERATION_BLOCKED: 'Blocked by the moderation policy',
  MODERATION_HELD: 'Held for review by the moderation policy',
  KILL_SWITCH: 'Stopped by a kill switch',
  MODEL_NOT_ALLOWED: 'Model not allowed for this risk tier',
  DRAFT_NOT_RELEASED: 'Draft agent not released for this use',
  PIPELINE_NODE_FAILED: 'A pipeline step failed',
  REQUIRED_TOOLS_VIOLATION: 'Agent skipped a required tool',
  GROUNDING_REQUIRED_VIOLATION: 'Agent answered without its knowledge base',
  CLIENT_DISCONNECTED: 'Caller left before the run finished',
  VALIDATION_FAILED: 'Output did not match the expected shape',
  RUNTIME_TIMEOUT: 'Run hit its time limit',
  REQUEST_TIMEOUT: 'An outside call took too long',
  EVAL_GATE: 'Held back by a failing evaluation',
  UNKNOWN_ERROR: 'Unclassified failure',
};

// an unmapped code still reads as words, never as SHOUTED_SNAKE_CASE
export function failureTitle(code: string | null | undefined): string {
  if (!code) return 'Unclassified failure';
  const known = FAILURE_TITLES[code];
  if (known) return known;
  const words = code.toLowerCase().replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Unclassified failure';
}
