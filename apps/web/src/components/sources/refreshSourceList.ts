import { mutate } from 'swr';
import { apiFetch } from '@/lib/api-client';

const LIST_KEYS = ['/api/sources', '/api/sources/changes?limit=12'];

// writes fresh rows into the SWR cache so the list is current even when it is not mounted
export async function refreshSourceList(): Promise<void> {
  await Promise.all(LIST_KEYS.map(async (key) => {
    const r = await apiFetch(key, { throwOnError: false, silent: true });
    if (r.error) await mutate(key);
    else await mutate(key, r, { revalidate: false });
  }));
}
