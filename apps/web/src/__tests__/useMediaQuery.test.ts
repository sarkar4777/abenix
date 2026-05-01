import { renderHook, act } from '@testing-library/react';
import { useMediaQuery, useIsMobile, useIsDesktop } from '@/hooks/useMediaQuery';

type MatchMediaHandler = (e: { matches: boolean }) => void;

let listeners: MatchMediaHandler[] = [];
let currentMatches = false;

beforeEach(() => {
  listeners = [];
  currentMatches = false;

  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: currentMatches,
      media: query,
      addEventListener: (_: string, handler: MatchMediaHandler) => {
        listeners.push(handler);
      },
      removeEventListener: (_: string, handler: MatchMediaHandler) => {
        listeners = listeners.filter((h) => h !== handler);
      },
    })),
  });
});

describe('useMediaQuery', () => {
  it('returns false initially on server (default state)', () => {
    currentMatches = false;
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    // After useEffect runs, it should reflect the matchMedia result
    expect(result.current).toBe(false);
  });

  it('returns true when matchMedia matches', () => {
    currentMatches = true;
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    expect(result.current).toBe(true);
  });

  it('updates when media query changes', () => {
    currentMatches = false;
    const { result } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    expect(result.current).toBe(false);

    act(() => {
      listeners.forEach((l) => l({ matches: true }));
    });
    expect(result.current).toBe(true);
  });

  it('cleans up listener on unmount', () => {
    currentMatches = false;
    const { unmount } = renderHook(() => useMediaQuery('(min-width: 768px)'));
    expect(listeners.length).toBe(1);
    unmount();
    expect(listeners.length).toBe(0);
  });
});

describe('useIsMobile', () => {
  it('returns true when viewport is narrow', () => {
    currentMatches = false; // (min-width: 768px) does NOT match → mobile
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it('returns false when viewport is wide', () => {
    currentMatches = true; // (min-width: 768px) matches → NOT mobile
    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });
});

describe('useIsDesktop', () => {
  it('returns true when viewport is wide', () => {
    currentMatches = true;
    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(true);
  });

  it('returns false when viewport is narrow', () => {
    currentMatches = false;
    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(false);
  });
});
