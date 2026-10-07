import { describe, expect, it } from 'vitest';
import { buildExampleArgs, fullDescription, schemaParams, tidyDescription } from '@/components/tools-catalogue/toolSchema';
import { adviceCode } from '@/components/alerts/failureAdvice';
import { pickRunnableModel } from '@/components/atlas/runnableModel';

const schema = {
  type: 'object',
  properties: {
    timezone: { type: 'string', description: 'IANA zone', default: 'UTC' },
    query: { type: 'string', description: 'What to search' },
    max_results: { type: 'integer', minimum: 1, maximum: 10 },
    mode: { type: 'string', enum: ['fast', 'deep'] },
    tags: { type: 'array', items: { type: 'string' } },
  },
  required: ['query', 'mode'],
};

describe('tool schema helpers', () => {
  it('lists required params first with readable types', () => {
    const params = schemaParams(schema);
    expect(params.map(p => p.name).slice(0, 2)).toEqual(['query', 'mode']);
    expect(params.find(p => p.name === 'tags')?.type).toBe('array of string');
    expect(params.find(p => p.name === 'timezone')).toMatchObject({ hasDefault: true, defaultValue: 'UTC', required: false });
    expect(params.find(p => p.name === 'mode')?.enumValues).toEqual(['fast', 'deep']);
  });

  it('builds example args from required params and defaults', () => {
    expect(buildExampleArgs(schema)).toEqual({ timezone: 'UTC', query: '<query>', mode: 'fast' });
  });

  it('falls back to the first param when nothing is required', () => {
    expect(buildExampleArgs({ type: 'object', properties: { n: { type: 'number', minimum: 3 } } })).toEqual({ n: 3 });
    expect(buildExampleArgs(undefined)).toEqual({});
    expect(schemaParams({ type: 'object' })).toEqual([]);
  });

  it('ends a cut description on a word with an ellipsis', () => {
    const cut = 'abcde '.repeat(70).slice(0, 400);
    const out = tidyDescription(cut);
    expect(out.endsWith('…')).toBe(true);
    expect(out).toMatch(/abcde…$/);
    expect(tidyDescription('Short and whole.')).toBe('Short and whole.');
  });

  it('prefers the longer generated description when it extends the API text', () => {
    const api = `${'a'.repeat(50)} cut`;
    const doc = `${'a'.repeat(50)} cut short by the list API but whole here.`;
    expect(fullDescription(api, doc)).toBe(doc);
    expect(fullDescription('Own text', 'Different text that is much longer than the API one')).toBe('Own text');
  });
});

describe('alert advice', () => {
  it('treats an old INFRA_AUTH_ERROR row with a revoked OAuth token as an LLM auth failure', () => {
    expect(adviceCode({ failure_code: 'INFRA_AUTH_ERROR', sample_message: 'Error code: 401 OAuth access token has been revoked' })).toBe('LLM_AUTH_ERROR');
    expect(adviceCode({ failure_code: 'INFRA_AUTH_ERROR', sample_message: 'HTTP 403 Forbidden from kube API' })).toBe('INFRA_AUTH_ERROR');
    expect(adviceCode({ failure_code: 'TOOL_ERROR', sample_message: 'oauth' })).toBe('TOOL_ERROR');
  });
});

describe('atlas default model', () => {
  const base = { status: 'available', is_deprecated: false, subscription_remapped_to: null, subscription_served: false };
  it('keeps a model that runs as itself', () => {
    expect(pickRunnableModel('gemini-2.5-pro', [{ ...base, value: 'gemini-2.5-pro' }], null)).toBe('gemini-2.5-pro');
  });
  it('switches to the model the subscription actually runs', () => {
    const models = [
      { ...base, value: 'gemini-2.5-pro', subscription_served: true, subscription_remapped_to: 'claude-haiku-4-5' },
      { ...base, value: 'claude-haiku-4-5', subscription_served: true },
    ];
    const sub = { active: true, exclusive: true, default_model: 'claude-haiku-4-5' };
    expect(pickRunnableModel('gemini-2.5-pro', models, sub)).toBe('claude-haiku-4-5');
  });
  it('leaves an unknown model alone without a subscription', () => {
    expect(pickRunnableModel('gemini-2.5-pro', [{ ...base, value: 'gpt-4o' }], null)).toBeNull();
  });
});
