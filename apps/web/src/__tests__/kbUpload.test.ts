import { afterEach, describe, expect, it, vi } from 'vitest';

import { uploadLargeFile } from '@/lib/kbUpload';

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify({ data }), { status, headers: { 'Content-Type': 'application/json' } });

afterEach(() => vi.unstubAllGlobals());

describe('uploadLargeFile', () => {
  it('sends the bytes as a raw stream when the API plans a stream', async () => {
    const calls: [string, RequestInit][] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push([url, init]);
        if (url.endsWith('/uploads')) return json([{ mode: 'stream', method: 'PUT', url: '/api/x/content' }]);
        return json({ id: 'd1' }, 201);
      }),
    );
    const file = new File(['hello'], 'a.txt', { type: 'text/plain' });
    const result = await uploadLargeFile('kb', file, { Authorization: 'Bearer t' });
    expect(result.document).toEqual({ id: 'd1' });
    expect(calls[1][1].method).toBe('PUT');
    expect(calls[1][1].body).toBe(file);
  });

  it('puts each S3 part and completes with its etag', async () => {
    const puts: number[] = [];
    let completed: unknown;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        if (url.endsWith('/uploads')) {
          return json([
            {
              mode: 'direct',
              upload: {
                kind: 's3_multipart',
                part_size: 3,
                parts: [
                  { part_number: 1, url: 'https://s3/1' },
                  { part_number: 2, url: 'https://s3/2' },
                ],
              },
              complete_url: '/api/x/complete',
              abort_url: '/api/x',
            },
          ]);
        }
        if (url.startsWith('https://s3/')) {
          puts.push((init.body as Blob).size);
          return new Response(null, { status: 200, headers: { ETag: `e${url.slice(-1)}` } });
        }
        completed = JSON.parse(init.body as string);
        return json({ id: 'd2' }, 201);
      }),
    );
    const result = await uploadLargeFile('kb', new File(['hello'], 'a.txt'), {});
    expect(puts.sort()).toEqual([2, 3]);
    expect(result.document).toEqual({ id: 'd2' });
    expect(completed).toEqual({
      parts: expect.arrayContaining([
        { part_number: 1, etag: 'e1' },
        { part_number: 2, etag: 'e2' },
      ]),
    });
  });

  it('aborts when a part fails and says why', async () => {
    const methods: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        methods.push(`${init.method} ${url}`);
        if (url.endsWith('/uploads')) {
          return json([
            {
              mode: 'direct',
              upload: { kind: 's3_multipart', part_size: 5, parts: [{ part_number: 1, url: 'https://s3/1' }] },
              complete_url: '/api/x/complete',
              abort_url: '/api/x',
            },
          ]);
        }
        if (url.startsWith('https://s3/')) return new Response(null, { status: 403 });
        return json({ aborted: true });
      }),
    );
    const result = await uploadLargeFile('kb', new File(['hello'], 'a.txt'), {});
    expect(result.error).toContain('part 1 was refused (403)');
    expect(methods.some((m) => m.startsWith('DELETE') && m.endsWith('/api/x'))).toBe(true);
  });

  it('returns an existing document without sending anything', async () => {
    const fetcher = vi.fn(async () => json([{ mode: 'duplicate', document: { id: 'same', duplicate: true } }]));
    vi.stubGlobal('fetch', fetcher);
    const result = await uploadLargeFile('kb', new File(['x'], 'a.txt'), {});
    expect(result.document).toEqual({ id: 'same', duplicate: true });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
