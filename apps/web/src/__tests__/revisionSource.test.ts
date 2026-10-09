import { SOURCE_BADGES, proofLink, sourceBadge } from '@/components/agent/revisionSource';

describe('revision source badge', () => {
  it('labels every source the API writes', () => {
    expect(sourceBadge('edit').label).toBe('Edit');
    expect(sourceBadge('healing').label).toBe('Healing');
    expect(sourceBadge('improvement').label).toBe('Improvement');
    expect(sourceBadge('revert').label).toBe('Revert');
    expect(sourceBadge('import').label).toBe('Import');
  });

  it('treats a missing or unknown source as an edit', () => {
    expect(sourceBadge(undefined)).toBe(SOURCE_BADGES.edit);
    expect(sourceBadge(null)).toBe(SOURCE_BADGES.edit);
    expect(sourceBadge('weird')).toBe(SOURCE_BADGES.edit);
  });
});

describe('proof link', () => {
  it('points at the agent improvements tab with the proposal', () => {
    expect(proofLink('a1', 'p 1')).toBe('/agents/a1/improvements?proposal=p%201');
  });

  it('is absent when the revision did not come from a proposal', () => {
    expect(proofLink('a1', null)).toBeNull();
    expect(proofLink('a1', undefined)).toBeNull();
  });
});
