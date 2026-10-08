import { describe, expect, it } from 'vitest';
import { apiErrorText, looksLikeCron, moderationCategoryLabel, withPending } from '@/lib/nav-walk';

describe('moderation labels', () => {
  it('names a custom pattern instead of custom:0', () => {
    expect(moderationCategoryLabel('custom:0', ['\bACCT-\d{6}\b'])).toBe('custom pattern 1 (\bACCT-\d{6}\b)');
    expect(moderationCategoryLabel('custom:4')).toBe('custom pattern 5');
    expect(moderationCategoryLabel('harassment')).toBe('harassment');
  });
});

describe('trigger form', () => {
  it('wants five cron fields', () => {
    expect(looksLikeCron('*/5 * * * *')).toBe(true);
    expect(looksLikeCron(' 0 9 * * 1-5 ')).toBe(true);
    expect(looksLikeCron('*/5 *')).toBe(false);
    expect(looksLikeCron('')).toBe(false);
  });

  it('reads the message out of an error object, never [object Object]', () => {
    expect(apiErrorText({ message: 'Invalid cron expression: 99 99 * * *', code: 400 }, 'x')).toBe('Invalid cron expression: 99 99 * * *');
    expect(apiErrorText('plain', 'x')).toBe('plain');
    expect(apiErrorText({ code: 500 }, 'fallback')).toBe('fallback');
  });
});

describe('meeting scope chips', () => {
  it('keeps text typed but not added', () => {
    expect(withPending(['status update'], ' pricing ')).toEqual(['status update', 'pricing']);
    expect(withPending(['pricing'], 'pricing')).toEqual(['pricing']);
    expect(withPending([], '  ')).toEqual([]);
  });
});
