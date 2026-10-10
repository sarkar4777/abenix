import { describe, expect, it } from 'vitest';
import { explainRunError } from '@/lib/run-errors';

describe('explainRunError', () => {
  it('names a pipeline time limit instead of blaming the provider', () => {
    const e = explainRunError(
      'The pipeline ran out of time. It stopped after 60s, the limit set in pipeline.timeout_seconds.',
    );
    expect(e?.title).toMatch(/time limit/);
  });

  it('names the agent rate limit instead of a busy provider', () => {
    const e = explainRunError('Triage is held to 2 runs per second by its rate limit. Try again in 1s.');
    expect(e?.title).toMatch(/runs per second/);
  });

  it('still reads a provider 429 as a busy provider', () => {
    expect(explainRunError('HTTP 429 Too Many Requests')?.title).toMatch(/busy/);
  });
});
