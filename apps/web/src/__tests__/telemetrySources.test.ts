import { describe, expect, it } from 'vitest';
import { addressOf, fieldProblem, initialValues, localSuggest, pushSnippets, subjectSummary, toPayload, type FieldDecl } from '@/lib/telemetry/sources';
import { mappingProblems } from '@/components/telemetry/MappingEditor';
import { needsMapping } from '@/components/telemetry/SourceWizard';
import { messageList } from '@/components/telemetry/MessagesTab';
import { optionsFor } from '@/components/telemetry/SendCommandDialog';
import { BLANK_MAPPING, cleanFilter, rulesToText, textToRules } from '@/lib/telemetry/sources';
import { diagnose } from '@/components/telemetry/SourceDiagnosis';
import { silentFor, valueFlags } from '@/lib/telemetry/format';

const KAFKA: FieldDecl[] = [
  { key: 'bootstrap_servers', label: 'Brokers', kind: 'list', required: true },
  { key: 'topic', kind: 'string', required: true },
  { key: 'group_id', kind: 'string', default: 'abenix' },
  { key: 'sasl_mechanism', kind: 'select', options: ['PLAIN', 'SCRAM-SHA-256', 'OAUTHBEARER'] },
  { key: 'password', kind: 'secret' },
  { key: 'ca_cert', kind: 'file', accept: '.pem,.crt' },
  { key: 'tls', kind: 'bool' },
  { key: 'poll_ms', kind: 'int' },
];

describe('generated source forms', () => {
  it('starts from defaults and keeps what the source already has', () => {
    const v = initialValues(KAFKA, { topic: 'payments.orders' });
    expect(v).toMatchObject({ topic: 'payments.orders', group_id: 'abenix', tls: false, password: '' });
  });
  it('says what is wrong at the field', () => {
    expect(fieldProblem(KAFKA[0], '')).toBe('Brokers is needed.');
    expect(fieldProblem(KAFKA[1], ' ')).toBe('Topic is needed.');
    expect(fieldProblem(KAFKA[7], '1.5')).toMatch(/whole number/);
    expect(fieldProblem(KAFKA[3], 'MD5')).toBe('Pick one of the options.');
    expect(fieldProblem({ key: 'url', kind: 'url', required: true, options: ['ws', 'wss'] }, 'http://x')).toBe('Start the address with ws:// or wss://.');
    expect(fieldProblem({ key: 'url', kind: 'url' }, 'opc.tcp://plc:4840')).toBeNull();
    // a stored secret counts as filled in
    expect(fieldProblem({ key: 'password', kind: 'secret', required: true }, '', true)).toBeNull();
  });
  it('sends lists as arrays and leaves kept secrets out', () => {
    const { config, secrets } = toPayload(KAFKA, { bootstrap_servers: 'a:9092\nb:9092', topic: 't', group_id: 'g', sasl_mechanism: 'PLAIN', password: '', ca_cert: '-----BEGIN', tls: true, poll_ms: '250' }, new Set(['password']));
    expect(config).toEqual({ bootstrap_servers: ['a:9092', 'b:9092'], topic: 't', group_id: 'g', sasl_mechanism: 'PLAIN', tls: true, poll_ms: 250 });
    expect(secrets).toEqual({ ca_cert: '-----BEGIN' });
  });
  it('summarises where a source reads from', () => {
    expect(subjectSummary({ topic: 'payments.orders' })).toEqual(['payments.orders']);
    expect(subjectSummary({}, ['spBv1.0/#'])).toEqual(['spBv1.0/#']);
    expect(addressOf({ bootstrap_servers: ['a:9092', 'b:9092'] })).toBe('a:9092, b:9092');
    expect(addressOf({ host: 'plc-1', port: 502 })).toBe('plc-1:502');
    expect(addressOf({}, 'mqtt://x:1883')).toBe('mqtt://x:1883');
  });
});

describe('mappings', () => {
  it('explains a curly bracket or a path it cannot use, and takes the rest', () => {
    expect(mappingProblems(BLANK_MAPPING)).toEqual({});
    expect(mappingProblems({ ...BLANK_MAPPING, node: '{payload.id}' }).templates).toMatch(/\{payload\.id\} is not something Abenix can fill in/);
    expect(mappingProblems({ ...BLANK_MAPPING, node: '{subject.2}', device: '{header.part}', group: 'site-{$.site}' })).toEqual({});
    expect(mappingProblems({ ...BLANK_MAPPING, timestamp: { path: '$.event time', format: 'auto' } }).paths).toMatch(/has a space/);
  });
  it('guesses the asset and the time from a JSON sample', () => {
    expect(localSuggest('{"asset":"pump-7","ts":1760000000000,"temperature_c":61.5}')).toEqual({
      node: '$.asset',
      timestamp: { path: '$.ts', format: 'epoch_ms' },
      signals: { include: [], exclude: ['$.asset', '$.ts'], flatten: true, units: {} },
    });
    expect(localSuggest('not json')).toBeNull();
  });
  it('skips the mapping step for formats that carry their own structure', () => {
    expect(needsMapping({ name: 'sparkplug_b', label: 'Sparkplug B', config_fields: [] })).toBe(false);
    expect(needsMapping({ name: 'can_frames', label: 'CAN', config_fields: [] })).toBe(false);
    expect(needsMapping({ name: 'json', label: 'JSON', config_fields: [] })).toBe(true);
    expect(needsMapping({ name: 'custom', label: 'x', config_fields: [], needs_mapping: false })).toBe(false);
  });
});

describe('push and messages', () => {
  it('builds copy-ready code with the endpoint and token', () => {
    const s = pushSnippets('http://localhost:8000/api/telemetry/ingest/abc', 'tok_123');
    expect(s.curl).toContain("curl -X POST 'http://localhost:8000/api/telemetry/ingest/abc'");
    expect(s.curl).toContain('Authorization: Bearer tok_123');
    expect(s.python).toContain('await forge.telemetry.ingest(');
    expect(s.python).toContain('base_url="http://localhost:8000"');
    expect(s.python).toContain('"abc"');
    expect(s.js).toContain("forge.telemetry.ingest(");
    expect(s.js).toContain("token: 'tok_123'");
    expect(pushSnippets('x', '').curl).toContain('<your source token>');
  });
  it('reads the inspector and dead-letter lists in either shape', () => {
    expect(messageList([{ subject: 'a' }])).toHaveLength(1);
    expect(messageList({ messages: [{ subject: 'a' }, { subject: 'b' }] })).toHaveLength(2);
    expect(messageList({ dlq: [{ reason: 'x' }] })).toHaveLength(1);
    expect(messageList(null)).toEqual([]);
  });
});

describe('write-back choices', () => {
  it('puts declared writable signals first and keeps the others apart', () => {
    const o = optionsFor({
      'Safety/Hold': { name: 'Safety/Hold', value: false, type: 'Boolean' },
      'Valve/Open_pct': { name: 'Valve/Open_pct', value: 40, type: 'Double', writable: true },
      'Flow_lph': { name: 'Flow_lph', value: 12, type: 'Double' },
    });
    expect(o.writable.map((w) => w.name)).toEqual(['Safety/Hold', 'Valve/Open_pct']);
    expect(o.writable[0].label).toBe('Safety hold');
    expect(o.others.map((w) => w.name)).toEqual(['Flow_lph']);
    expect(o.others[0].help).toMatch(/not declared writable/);
  });
});

describe('why nothing shows', () => {
  const base = { id: 's1', name: 'Payments stream', broker_url: '', topics: [], enabled: true, transport: 'kafka', config: { topic: 'payments.orders' } } as any;
  it('names the one thing to do for each way of seeing nothing', () => {
    expect(diagnose({ ...base, enabled: false }, { canManage: true, assets: 0 })).toMatchObject({ tone: 'off', action: { kind: 'turn_on' } });
    expect(diagnose({ ...base, enabled: false }, { canManage: false, assets: 0 }).text).toMatch(/An admin can turn it on/);
    expect(diagnose({ ...base, status: 'error', last_error: 'Connection refused' }, { canManage: true, assets: 0 })).toMatchObject({ tone: 'bad', action: { kind: 'edit' } });
    expect(diagnose({ ...base, status: 'connected' }, { canManage: true, assets: 0 }).text).toMatch(/connected but nothing has arrived yet\. It reads payments\.orders/);
    expect(diagnose({ ...base, status: 'connected', transport: 'http_push' }, { canManage: true, assets: 0 })).toMatchObject({ action: { kind: 'endpoint' } });
    expect(diagnose({ ...base, status: 'connected', last_message_at: 'x', dlq_count: 3 }, { canManage: false, assets: 0 })).toMatchObject({ tone: 'warn', action: { kind: 'problems' } });
    expect(diagnose({ ...base, status: 'connected', last_message_at: 'x', dlq_count: 0 }, { canManage: true, assets: 0 }).text).toMatch(/the mapping keeps nothing/);
    expect(diagnose({ ...base, status: 'connected', last_message_at: 'x' }, { canManage: true, assets: 4 }).tone).toBe('ok');
  });
  it('marks bad, uncertain and clock-ahead values, and an asset gone quiet', () => {
    const now = 1_760_000_000_000;
    expect(valueFlags({ quality: 192 }, now)).toEqual([]);
    expect(valueFlags({ quality: 0 }, now)).toEqual(['bad']);
    expect(valueFlags({ quality: 'uncertain' }, now)).toEqual(['uncertain']);
    expect(valueFlags({ quality: 'good', ts: now + 60_000 }, now)).toEqual(['ahead']);
    expect(silentFor(now - 120_000, true, now)).toBe(120_000);
    expect(silentFor(now - 5_000, true, now)).toBeNull();
    expect(silentFor(now - 120_000, false, now)).toBeNull();
  });
});

describe('mapping filter', () => {
  it('reads and writes path = value lines', () => {
    expect(textToRules('$.type = tick\n$.side = buy, sell')).toEqual({ rules: { '$.type': 'tick', '$.side': ['buy', 'sell'] }, problem: null });
    expect(textToRules('$.type tick').problem).toMatch(/needs a path, an equals sign and a value/);
    expect(textToRules('$.type =').problem).toMatch(/no value/);
    expect(rulesToText({ '$.type': ['subscribed', 'heartbeat'] })).toBe('$.type = subscribed, heartbeat');
  });
  it('leaves an empty filter out of the mapping', () => {
    expect(cleanFilter({ require: [], match: {}, exclude: {} })).toBeNull();
    expect(cleanFilter({ require: ['$.symbol'], match: {} })).toEqual({ require: ['$.symbol'] });
  });
  it('says when the filter skips everything', () => {
    const d = diagnose({ id: 's', name: 'Ticks', enabled: true, status: 'connected', last_message_at: 'x', pipeline: { skipped: 40, stored: 0, last_reasons: { skipped: { reason: 'The type was heartbeat.' } } } } as never, { canManage: true, assets: 0 });
    expect(d.text).toBe('Messages arrive from Ticks, but its filter skips every one, the last because the type was heartbeat. Check which messages the mapping keeps.');
    expect(d.action?.kind).toBe('mapping');
  });
});
