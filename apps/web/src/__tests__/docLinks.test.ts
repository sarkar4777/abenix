import { describe, expect, it } from 'vitest';
import { DOCS_REPO, resolveDocHref } from '@/lib/doc-links';

describe('resolveDocHref', () => {
  it('keeps a sibling doc in its folder', () => {
    expect(resolveDocHref('00-local-setup.md', '08-howto/04-debugging').href).toBe('?slug=08-howto%2F00-local-setup');
  });
  it('walks up to another section and keeps the anchor', () => {
    expect(resolveDocHref('../02-runtime/00-agent-execution.md#loop', '08-howto/13-earned-autonomy').href)
      .toBe('?slug=02-runtime%2F00-agent-execution#loop');
  });
  it('sends source files to the repo', () => {
    const r = resolveDocHref('../../packages/db/models/autonomy.py', '04-data-model/08-autonomy');
    expect(r).toEqual({ href: `${DOCS_REPO}/packages/db/models/autonomy.py`, external: true });
    expect(resolveDocHref('../apps/api/app/main.py#L75', 'README').href).toBe(`${DOCS_REPO}/apps/api/app/main.py#L75`);
  });
  it('leaves web links and anchors alone', () => {
    expect(resolveDocHref('https://x.dev/a', 'README')).toEqual({ href: 'https://x.dev/a', external: true });
    expect(resolveDocHref('#top', 'README').href).toBe('#top');
  });
});
