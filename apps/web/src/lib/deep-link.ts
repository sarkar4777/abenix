import { useEffect, useRef, useState } from 'react';

export type DeepLinkState = 'none' | 'waiting' | 'found' | 'missing';

// first non-empty value among the given query keys, so ?asset= and ?id= both work
export function deepLinkParam(
  params: { get(key: string): string | null } | null | undefined,
  keys: string[],
): string | null {
  if (!params) return null;
  for (const k of keys) {
    const v = params.get(k)?.trim();
    if (v) return v;
  }
  return null;
}

export function resolveDeepLink<T extends { id: string }>(
  items: T[] | null | undefined,
  wanted: string | null,
  match: (item: T, wanted: string) => boolean = (item, w) => item.id === w,
): { state: DeepLinkState; item: T | null } {
  if (!wanted) return { state: 'none', item: null };
  if (!items) return { state: 'waiting', item: null };
  const item = items.find((i) => match(i, wanted)) ?? null;
  return { state: item ? 'found' : 'missing', item };
}

// a name can stand in for an id, the active version wins, then the newest listed
export function matchModel(m: { id: string; name: string; is_active?: boolean }, wanted: string, all: { id: string; name: string; is_active?: boolean }[]): boolean {
  if (m.id === wanted) return true;
  if (all.some((x) => x.id === wanted)) return false;
  const named = all.filter((x) => x.name === wanted);
  if (!named.length) return false;
  const pick = named.find((x) => x.is_active) ?? named[0];
  return pick.id === m.id;
}

// opens the linked item once per id, later clicks are left alone
export function useDeepLink<T extends { id: string }>(
  items: T[] | null | undefined,
  wanted: string | null,
  open: (item: T) => void,
  match?: (item: T, wanted: string) => boolean,
): string | null {
  const applied = useRef<string | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  useEffect(() => {
    if (!wanted) {
      applied.current = null;
      setMissing(null);
      return;
    }
    if (applied.current === wanted) return;
    const { state, item } = resolveDeepLink(items, wanted, match);
    if (state === 'waiting') return;
    applied.current = wanted;
    if (state === 'found' && item) {
      setMissing(null);
      open(item);
    } else {
      setMissing(wanted);
    }
  }, [items, wanted]);
  return missing;
}

// scrolls the list row tagged data-deeplink-id into view once it has rendered
export function scrollToDeepLinkRow(id: string, scroll: (el: Element | null) => void): void {
  if (typeof window === 'undefined') return;
  window.setTimeout(() => {
    const sel = `[data-deeplink-id="${typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(id) : id}"]`;
    scroll(document.querySelector(sel));
  }, 50);
}
