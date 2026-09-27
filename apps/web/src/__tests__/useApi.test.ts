import { renderHook, waitFor } from '@testing-library/react';
import { useApi } from '@/hooks/useApi';

const mockFetch = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  mockFetch.mockReset();

  // Mock localStorage for token
  Object.defineProperty(window, 'localStorage', {
    writable: true,
    value: {
      getItem: vi.fn().mockReturnValue('test-token'),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    },
  });

  // Mock global fetch
  global.fetch = mockFetch;
});

describe('useApi', () => {
  it('returns null data when path is null', () => {
    const { result } = renderHook(() => useApi(null));
    expect(result.current.data).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it('fetches data and returns the data field', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          data: { name: 'Test Agent' },
          error: null,
          meta: { total: 1 },
        }),
    });

    const { result } = renderHook(() =>
      useApi<{ name: string }>('/api/agents/1'),
    );

    await waitFor(() => {
      expect(result.current.data).toEqual({ name: 'Test Agent' });
    });

    expect(result.current.error).toBeNull();
    expect(result.current.meta).toEqual({ total: 1 });
  });

  it('returns error when API responds with error', async () => {
    // The envelope only ever carries a non-null `error` alongside a non-2xx
    // status — `success()` on the API side always writes error: null. This
    // used to mock ok: true with an error body, which apiFetch reports as a
    // success with no error, so the assertion could never hold. It went
    // unnoticed because nothing ran this suite.
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      headers: { get: () => null },
      json: () =>
        Promise.resolve({
          data: null,
          error: { message: 'Not found', code: 404, error_code: 'NOT_FOUND' },
          meta: null,
        }),
    });

    const { result } = renderHook(() => useApi('/api/agents/999'));

    await waitFor(() => {
      expect(result.current.error).toBe('Not found');
    });

    expect(result.current.data).toBeNull();
  });

  it('provides a mutate function to refetch', async () => {
    let callCount = 0;
    mockFetch.mockImplementation(() => {
      callCount++;
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            data: { count: callCount },
            error: null,
            meta: null,
          }),
      });
    });

    const { result } = renderHook(() =>
      useApi<{ count: number }>('/api/data'),
    );

    await waitFor(() => {
      expect(result.current.data).toBeTruthy();
    });

    expect(typeof result.current.mutate).toBe('function');
  });
});
