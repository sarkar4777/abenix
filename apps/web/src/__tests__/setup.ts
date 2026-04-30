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

Object.defineProperty(globalThis, 'AbortController', {
  value: class {
    signal = { aborted: false };
    abort() {
      (this.signal as { aborted: boolean }).aborted = true;
    }
  },
});
