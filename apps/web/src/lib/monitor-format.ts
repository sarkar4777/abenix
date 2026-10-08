// Plain words for the codes and metrics the monitor pages show.

const FAILURE_LABELS: Record<string, string> = {
  LLM_RATE_LIMIT: 'AI provider rate limit',
  LLM_PROVIDER_ERROR: 'AI provider error',
  LLM_AUTH_ERROR: 'AI provider sign-in failed',
  LLM_INVALID_RESPONSE: 'Unreadable AI answer',
  INFRA_AUTH_ERROR: 'Sign-in to a service failed',
  SANDBOX_TIMEOUT: 'Code ran too long',
  SANDBOX_NONZERO_EXIT: 'Code exited with an error',
  SANDBOX_OOM: 'Code ran out of memory',
  SANDBOX_IMAGE_BLOCKED: 'Code image not allowed',
  TOOL_NOT_FOUND: 'Unknown tool',
  TOOL_ERROR: 'A tool failed',
  PIPELINE_NODE_FAILED: 'A pipeline step failed',
  BUDGET_EXCEEDED: 'Spending limit reached',
  MODERATION_BLOCKED: 'Blocked by moderation',
  TIMEOUT: 'Timed out',
  STALE_SWEPT: 'Stopped responding',
  KILL_SWITCH: 'Stopped by a kill switch',
};

export function failureLabel(code: string | null | undefined): string {
  if (!code) return '';
  const known = FAILURE_LABELS[code];
  if (known) return known;
  const words = code.toLowerCase().split(/[_\s.]+/).filter(Boolean).join(' ');
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : code;
}

const METRIC_LABELS: Record<string, string> = {
  confidence: 'Confidence',
  input_tokens: 'Input tokens',
  output_tokens: 'Output tokens',
  output_length: 'Answer length',
  duration_ms: 'Run time',
  latency_ms: 'Run time',
  cost: 'Cost',
  tool_calls: 'Tool calls',
  tool_failure_rate: 'Tool failure rate',
};

export function metricLabel(name: string): string {
  return METRIC_LABELS[name] || failureLabel(name.toUpperCase());
}

function num(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Math.abs(v) >= 100) return Math.round(v).toLocaleString();
  return v.toFixed(2).replace(/\.?0+$/, '') || '0';
}

// a percent off a zero baseline is noise, so say what it went from and to
export function driftChange(a: { metric_name: string; baseline_value: number; current_value: number; deviation_pct: number }): string {
  const label = metricLabel(a.metric_name);
  const up = a.current_value >= a.baseline_value;
  const verb = up ? 'rose' : 'fell';
  if (Math.abs(a.baseline_value) < 0.01) return `${label} ${verb} from ${num(a.baseline_value)} to ${num(a.current_value)}, there was no usual level yet`;
  const pct = Math.abs(a.deviation_pct);
  const pctText = pct >= 1000 ? `${Math.round(pct / 100)}x` : `${Math.round(pct)}%`;
  return `${label} ${verb} ${pctText}, from a usual ${num(a.baseline_value)} to ${num(a.current_value)}`;
}

export function roleLabel(role: string | null | undefined): string {
  if (role === 'admin') return 'Admin';
  if (role === 'creator') return 'Creator';
  return 'Member';
}

const SETTING_TITLES: Record<string, string> = {
  'ai_builder.model': 'Builder model',
  'ai_builder.critic.model': 'Builder critic model',
  'ai_builder.validation.model': 'Preview and validation model',
  'moderation.model': 'Moderation model',
  'knowledge_engine.summarizer.model': 'Document summary model',
  'sdk_playground.default.model': 'SDK Playground default model',
  'triggers.default.model': 'Trigger default model',
  'pipeline_surgeon.model': 'Pipeline Surgeon model',
  'workflow_shell.model': 'Talk-to-workflow model',
  'pipeline.timeout_seconds': 'Pipeline time limit (seconds)',
  'agent.max_iterations': 'Agent step limit',
  'sandbox.timeout_seconds': 'Sandbox time limit (seconds)',
  'llm.subscription.token': 'Subscription token',
  'llm.subscription.default_model': 'Model the subscription serves',
};

export function settingTitle(key: string): string {
  if (SETTING_TITLES[key]) return SETTING_TITLES[key];
  const words = key.split('.').join(' ').split('_').join(' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}
