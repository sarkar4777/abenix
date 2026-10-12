import { describe, expect, it } from 'vitest';
import { deviceIdProblem, deviceSnippets, ingestError, keysToCsv, parseKeysCsv } from '@/lib/telemetry/keys';

describe('device keys', () => {
  it('checks a device id at the field', () => {
    expect(deviceIdProblem('')).toMatch(/Give the device id/);
    expect(deviceIdProblem('van 42')).toMatch(/cannot contain spaces/);
    expect(deviceIdProblem('van/42')).toMatch(/cannot contain/);
    expect(deviceIdProblem('van-042')).toBeNull();
  });
  it('reads a CSV with or without a header and says which lines need fixing', () => {
    const a = parseKeysCsv('device_id,label,group\nvan-1,"Transit, depot B",north\nvan-2,,north\nvan-1,dup,\n bad id ,x,y');
    expect(a.problem).toBeNull();
    expect(a.rows.map((r) => [r.device_id, r.label, r.group])).toEqual([['van-1', 'Transit, depot B', 'north'], ['van-2', '', 'north'], ['van-1', 'dup', ''], ['bad id', 'x', 'y']]);
    expect(a.rows[2].problem).toMatch(/earlier line/);
    expect(a.rows[3].problem).toMatch(/spaces/);
    expect(parseKeysCsv('m-1\nm-2').rows.map((r) => r.device_id)).toEqual(['m-1', 'm-2']);
    expect(parseKeysCsv('').problem).toMatch(/device_id column/);
    const many = Array.from({ length: 5001 }, (_, i) => `d-${i}`).join('\n');
    expect(parseKeysCsv(many).problem).toMatch(/Up to 5000/);
  });
  it('writes the made keys back out as CSV', () => {
    expect(keysToCsv([{ id: '1', kind: 'device', device_id: 'van-1', label: 'a,b', group: 'n', key: 'tdk_x' }])).toBe('device_id,label,group,key\nvan-1,"a,b",n,tdk_x');
  });
  it('gives code that sends as the device, with an idempotency key', () => {
    const s = deviceSnippets('http://x/api/telemetry/ingest/s1', 'tdk_abc', 'van-1');
    expect(s.curl).toContain('Authorization: Bearer tdk_abc');
    expect(s.curl).toContain('Idempotency-Key: van-1-');
    expect(s.python).toContain('idempotency_key=str(uuid.uuid4())');
    expect(s.python).toContain('import uuid');
    expect(s.python).toContain('token="tdk_abc"');
    expect(s.js).toContain('idempotencyKey: crypto.randomUUID()');
  });
  it('turns ingest refusals into plain words', () => {
    expect(ingestError(401, 'UNAUTHORIZED')).toMatch(/refused/);
    expect(ingestError(409, 'DISABLED')).toMatch(/turned off/);
    expect(ingestError(413, 'PAYLOAD_TOO_LARGE')).toMatch(/size limit, 1 MB/);
    expect(ingestError(415, 'UNSUPPORTED_MEDIA_TYPE')).toMatch(/JSON, one JSON per line, CSV or plain text/);
  });
});
