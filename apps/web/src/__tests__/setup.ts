import '@testing-library/jest-dom/vitest';

const localStorageMock: Storage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
    get length() {
      return Object.keys(store).length;
    },
    key: (index: number) => Object.keys(store)[index] ?? null,
  };
})();

Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock });

globalThis.fetch = vi.fn();

// jsdom supplies a real AbortController now. The hand-rolled stub that used to
// live here handed back a bare `{ aborted: false }` as its signal, and vitest 4
// calls signal.addEventListener internally, so every test died in setup with
// "signal.addEventListener is not a function". Nothing needs the stub.
if (typeof globalThis.AbortController !== 'function') {
  throw new Error('test environment provides no AbortController');
}
