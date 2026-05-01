'use client';

import useSWR, { type SWRConfiguration } from 'swr';
import { apiFetch } from '@/lib/api-client';

interface UseApiResult<T> {
  data: T | null;
  error: string | null;
  meta: Record<string, unknown> | null;
  isLoading: boolean;
  mutate: () => void;
}

export function useApi<T = unknown>(
  path: string | null,
  options?: SWRConfiguration,
): UseApiResult<T> {
  const { data: response, error: swrError, isLoading, mutate } = useSWR(
    path,
    (url: string) => apiFetch<T>(url),
    {
      revalidateOnFocus: false,
      dedupingInterval: 5000,
      ...options,
    },
  );

  return {
    data: response?.data ?? null,
    error: response?.error ?? (swrError ? String(swrError) : null),
    meta: response?.meta ?? null,
    isLoading,
    mutate: () => { mutate(); },
  };
}
