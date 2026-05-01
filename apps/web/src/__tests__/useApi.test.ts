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
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          data: null,
          error: 'Not found',
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
