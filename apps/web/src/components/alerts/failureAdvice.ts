export const LLM_AUTH_FOR_USERS = 'The AI model provider rejected the platform\u2019s sign-in, so these runs never reached the model. Ask an admin to reconnect the AI model.';

// rows classified before LLM_AUTH_ERROR existed still carry INFRA_AUTH_ERROR
const LLM_AUTH_SAMPLE = /oauth|access token|token has been revoked|authentication_error|api[ _-]?key/i;

export function adviceCode(g: { failure_code: string; sample_message?: string | null }): string {
  if (g.failure_code === 'INFRA_AUTH_ERROR' && LLM_AUTH_SAMPLE.test(g.sample_message || '')) return 'LLM_AUTH_ERROR';
  return g.failure_code;
}
