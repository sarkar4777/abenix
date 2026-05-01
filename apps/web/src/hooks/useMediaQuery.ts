'use client';

import { useState, useEffect } from 'react';

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(query);
    setMatches(mql.matches);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

export function useIsMobile(): boolean {
  return !useMediaQuery('(min-width: 768px)');
}

export function useIsTablet(): boolean {
  const isMd = useMediaQuery('(min-width: 768px)');
  const isLg = useMediaQuery('(min-width: 1024px)');
  return isMd && !isLg;
}

export function useIsDesktop(): boolean {
  return useMediaQuery('(min-width: 1024px)');
}
