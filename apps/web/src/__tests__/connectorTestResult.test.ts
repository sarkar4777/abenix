import { describe, expect, it } from 'vitest';
import { describeTest, type TestResult } from '@/app/(app)/admin/connectors/test-result';

const base: TestResult = { ok: false, latency_ms: 12, status_code: null, sample_response_excerpt: null, error: null };

describe('describeTest', () => {
  it('uses the server message when there is one', () => {
    const msg = 'Blocked: 10.0.0.5 is a private or loopback address. Connectors may only call public addresses.';
    expect(describeTest({ ...base, blocked: true, message: msg, error: msg })).toBe(msg);
  });
  it('says reached for 2xx and 3xx', () => {
    expect(describeTest({ ...base, ok: true, status_code: 200 })).toMatch(/^Reached it, HTTP 200/);
    expect(describeTest({ ...base, ok: true, status_code: 302 })).toMatch(/redirect/);
  });
  it('says the credentials were refused for 401 and 403', () => {
    expect(describeTest({ ...base, status_code: 401 })).toMatch(/refused the credentials/);
    expect(describeTest({ ...base, status_code: 403 })).toMatch(/refused the credentials/);
  });
  it('falls back to the error text from an older server', () => {
    expect(describeTest({ ...base, error: 'connector test failed: boom' })).toBe('Could not reach it: boom');
  });
});
