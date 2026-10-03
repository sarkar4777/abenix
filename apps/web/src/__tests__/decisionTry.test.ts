import { describe, expect, it } from 'vitest';
import { readTryPreload, tryHref } from '@/lib/decisions';

describe('Try preload links', () => {
  it('round-trips small facts through the URL', () => {
    const href = tryHref('freight.surcharge', 3, { facts: { shipment: { postcode: 'IV27' } }, as_of: '2026-03-14' });
    const url = new URL(href, 'http://x');
    expect(url.pathname).toBe('/decisions/freight.surcharge');
    expect(url.searchParams.get('version')).toBe('3');
    expect(readTryPreload('freight.surcharge', url.searchParams.get('try'))).toEqual({ facts: { shipment: { postcode: 'IV27' } }, as_of: '2026-03-14' });
  });

  it('keeps large facts in session storage for the same decision only', () => {
    const facts = { blob: 'x'.repeat(8000) };
    const url = new URL(tryHref('k', 1, { facts }), 'http://x');
    expect(url.searchParams.get('try')).toBe('session');
    expect(readTryPreload('k', 'session')?.facts).toEqual(facts);
    expect(readTryPreload('other', 'session')).toBeNull();
  });

  it('ignores junk', () => {
    expect(readTryPreload('k', null)).toBeNull();
    expect(readTryPreload('k', '{not json')).toBeNull();
    expect(readTryPreload('k', '[1]')).toBeNull();
    expect(readTryPreload('k', '{"facts": [1]}')).toEqual({ facts: {}, as_of: null });
  });
});
