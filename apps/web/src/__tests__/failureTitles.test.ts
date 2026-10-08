import { describe, expect, it } from 'vitest';
import { FAILURE_TITLES, failureTitle } from '@/components/alerts/failureAdvice';

const RAW_CODE = /\b[A-Z]+(?:_[A-Z]+)*_(?:ERROR|FAILED|TIMEOUT|EXCEEDED|DENIED|NOT_FOUND|NOT_ALLOWED|INVALID|FORBIDDEN|VIOLATION|BLOCKED)\b/;

describe('failure titles', () => {
  it('leads with plain words for the AI sign-in failure', () => {
    expect(failureTitle('LLM_AUTH_ERROR')).toBe('AI provider sign-in failed');
  });

  it('has a friendly title for every code the alerts page describes', () => {
    const codes = [
      'LLM_RATE_LIMIT', 'LLM_PROVIDER_ERROR', 'LLM_INVALID_RESPONSE', 'LLM_AUTH_ERROR', 'CONFIG_UNKNOWN_MODEL',
      'SANDBOX_TIMEOUT', 'SANDBOX_NONZERO_EXIT', 'SANDBOX_OOM', 'SANDBOX_IMAGE_BLOCKED', 'TOOL_NOT_FOUND', 'TOOL_ERROR',
      'BUDGET_EXCEEDED', 'RATE_LIMITED', 'STALE_SWEEP', 'INFRA_CRASH', 'INFRA_AUTH_ERROR', 'MODERATION_BLOCKED',
      'KILL_SWITCH', 'MODEL_NOT_ALLOWED', 'PIPELINE_NODE_FAILED', 'REQUIRED_TOOLS_VIOLATION',
      'GROUNDING_REQUIRED_VIOLATION', 'CLIENT_DISCONNECTED', 'VALIDATION_FAILED', 'RUNTIME_TIMEOUT', 'REQUEST_TIMEOUT',
      'UNKNOWN_ERROR',
    ];
    for (const c of codes) expect(FAILURE_TITLES[c], c).toBeTruthy();
  });

  it('never reads like a raw code', () => {
    for (const [code, title] of Object.entries(FAILURE_TITLES)) {
      expect(title, code).not.toMatch(RAW_CODE);
      expect(title, code).not.toMatch(/_/);
    }
  });

  it('turns an unmapped code into words', () => {
    expect(failureTitle('QUEUE_FULL_ERROR')).toBe('Queue full error');
    expect(failureTitle('')).toBe('Unclassified failure');
    expect(failureTitle(null)).toBe('Unclassified failure');
  });
});
