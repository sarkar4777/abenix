import { beforeEach, describe, expect, it, vi } from 'vitest';

const calls: Array<{ path: string; opts: any }> = [];
let replies: any[] = [];
vi.mock('@/lib/api-client', () => ({
  apiFetch: vi.fn(async (path: string, opts: any) => {
    calls.push({ path, opts });
    return replies.shift();
  }),
}));

import { forgetAll, forgetOne, forgetPreview, globProblem, offlineLabel } from '@/lib/telemetry/forget';

beforeEach(() => { calls.length = 0; replies = []; });

describe('forget one', () => {
  it('forgets a part, or the whole asset when no part is given', async () => {
    replies = [{ data: { forgotten: 1 }, error: null }, { data: { devices: [{}, {}, {}] }, error: null }];
    expect(await forgetOne('fleet', 'van-7', 'engine')).toEqual({ kind: 'done', count: 1 });
    expect(calls[0].path).toBe('/api/telemetry/devices/fleet/van-7?device=engine&force=false');
    expect(calls[0].opts.method).toBe('DELETE');
    expect(await forgetOne('fleet', 'van-7', null, true)).toEqual({ kind: 'done', count: 3 });
    expect(calls[1].path).toBe('/api/telemetry/devices/fleet/van-7?force=true');
  });
  it('asks again when the device is online, and says other refusals plainly', async () => {
    replies = [
      { data: null, error: 'van-7 is online, it would come straight back.', errorDetail: { code: 409, error_code: 'DEVICE_ONLINE' } },
      { data: null, error: 'Forbidden', errorDetail: { code: 403, error_code: 'FORBIDDEN' } },
    ];
    expect(await forgetOne('fleet', 'van-7', null)).toEqual({ kind: 'online', message: 'van-7 is online, it would come straight back.' });
    const r = await forgetOne('fleet', 'van-7', null);
    expect(r.kind).toBe('error');
  });
});

describe('forget many', () => {
  it('previews with a dry run', async () => {
    replies = [{ data: { dry_run: true, matched: 1250, forgotten: 0, remaining: 1250, sample: [] }, error: null }];
    const r = await forgetPreview({ offline_for_s: 3600, node_glob: 'SHP*' });
    expect(r.result?.matched).toBe(1250);
    expect(JSON.parse(calls[0].opts.body)).toEqual({ offline_for_s: 3600, node_glob: 'SHP*', dry_run: true });
  });
  it('keeps going while some remain, and reports progress', async () => {
    replies = [
      { data: { dry_run: false, matched: 2500, forgotten: 2000, remaining: 500, sample: [] }, error: null },
      { data: { dry_run: false, matched: 500, forgotten: 500, remaining: 0, sample: [] }, error: null },
    ];
    const seen: Array<[number, number]> = [];
    const r = await forgetAll({ offline_for_s: 3600 }, (d, rem) => seen.push([d, rem]));
    expect(r).toEqual({ forgotten: 2500, error: null });
    expect(seen).toEqual([[2000, 500], [2500, 0]]);
    expect(calls).toHaveLength(2);
  });
  it('checks the name pattern and names the offline span', () => {
    expect(globProblem('uat *')).toMatch(/cannot contain spaces/);
    expect(globProblem('uat-*')).toBeNull();
    expect(offlineLabel(3600)).toBe('more than 1 hour');
  });
});
