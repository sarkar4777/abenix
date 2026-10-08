// Where a link inside a developer doc should go when read in the app.

export const DOCS_REPO = 'https://github.com/sarkar4777/abenix/blob/main';

function normalise(parts: string[]): string[] | null {
  const out: string[] = [];
  for (const p of parts) {
    if (!p || p === '.') continue;
    if (p === '..') {
      if (!out.length) return null;
      out.pop();
    } else out.push(p);
  }
  return out;
}

export function resolveDocHref(href: string, currentSlug: string): { href: string; external: boolean } {
  if (!href || /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith('#')) {
    return { href, external: /^https?:/i.test(href) };
  }
  const cut = href.search(/[?#]/);
  const path = cut >= 0 ? href.slice(0, cut) : href;
  const fragment = cut >= 0 ? href.slice(cut) : '';
  // docs live under docs/ in the repo, slugs are relative to it
  const base = href.startsWith('/') ? [] : ['docs', ...currentSlug.split('/').slice(0, -1)];
  const parts = normalise([...base, ...path.replace(/^\//, '').split('/')]);
  if (!parts) return { href, external: false };
  if (parts[0] === 'docs' && /\.md$/i.test(path)) {
    const slug = parts.slice(1).join('/').replace(/\.md$/i, '');
    return { href: `?slug=${encodeURIComponent(slug)}${fragment}`, external: false };
  }
  return { href: `${DOCS_REPO}/${parts.join('/')}${fragment}`, external: true };
}
