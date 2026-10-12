import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

const apiCalls: { path: string; init?: any }[] = [];
let apiReply: (path: string, init?: any) => any = () => ({ data: null, error: null });

vi.mock('@/lib/api-client', async (orig) => {
  const actual = await orig<typeof import('@/lib/api-client')>();
  return {
    ...actual,
    apiFetch: vi.fn(async (path: string, init?: any) => {
      apiCalls.push({ path, init });
      return apiReply(path, init);
    }),
  };
});

import PushPanel from '@/components/telemetry/PushPanel';
import MappingEditor from '@/components/telemetry/MappingEditor';
import { BLANK_MAPPING, fieldHelp, fieldShown, pushSnippets, pushSubject, LIST_HINT, type FieldDecl } from '@/lib/telemetry/sources';
import { deviceSnippets } from '@/lib/telemetry/keys';
import { testbedServiceFor, testbedSummary, testbedValues } from '@/lib/telemetry/testbed';
import { captureReason } from '@/lib/telemetry/errors';

beforeEach(() => {
  apiCalls.length = 0;
  apiReply = () => ({ data: null, error: null });
});

describe('push snippet matches the mapping (W3) with a fresh idempotency key (gap 7)', () => {
  const sample = JSON.stringify({ vehicle_id: 'VAN-042', speed_kmh: 48, ignition: true });
  it('sends the guide sample, not a generic pump', () => {
    const s = pushSnippets('http://x/api/telemetry/ingest/abc', 't', { sample, mapping: { group: 'fleet', node: '$.vehicle_id' } });
    expect(s.curl).toContain('VAN-042');
    expect(s.curl).not.toContain('pump-7');
    expect(s.python).toContain('"ignition": True');
    expect(s.js).toContain('"vehicle_id":"VAN-042"');
  });
  it('adds a subject when the mapping takes the asset from the topic', () => {
    expect(pushSubject({ group: 'fleet', node: '' })).toBe('fleet/device-1');
    expect(pushSubject({ group: 'fleet', node: '$.vehicle_id' })).toBeNull();
    const s = pushSnippets('http://x/api/telemetry/ingest/abc', 't', { mapping: { group: 'fleet', node: '' } });
    expect(s.curl).toContain('?subject=fleet%2Fdevice-1');
    expect(s.python).toContain('subject="fleet/device-1"');
    expect(s.js).toContain("subject: 'fleet/device-1'");
  });
  it('makes a new idempotency key on every send', () => {
    const s = pushSnippets('http://x/api/telemetry/ingest/abc', 't');
    expect(s.curl).toContain('Idempotency-Key: $(date +%s)-$RANDOM');
    expect(s.curl).not.toMatch(/1760175000000/);
    expect(s.python).toContain('idempotency_key=str(uuid.uuid4())');
    expect(s.python).toContain('import uuid');
    expect(s.js).toContain('idempotencyKey: crypto.randomUUID()');
    expect(deviceSnippets('http://x/api/telemetry/ingest/abc', 'k', 'dev-1').curl).toContain('dev-1-$(date +%s)-$RANDOM');
  });
});

describe('send a test message works without the plain token (W4)', () => {
  it('posts to the server-side test endpoint and says where it landed', async () => {
    apiReply = (path) => (path.endsWith('/test-message') ? { data: { stored: true, group: 'fleet', node: 'VAN-042' }, error: null } : { data: null, error: null });
    render(<PushPanel sourceId="src-1" token={null} testBody={'{"vehicle_id":"VAN-042"}'} mapping={{ group: 'fleet', node: '$.vehicle_id' }} />);
    const btn = screen.getByTestId('tel-push-test');
    expect(btn).not.toBeDisabled();
    await act(async () => { fireEvent.click(btn); });
    const call = apiCalls.find((c) => c.path === '/api/telemetry/connections/src-1/test-message');
    expect(call).toBeTruthy();
    expect(JSON.parse(call!.init.body).payload).toContain('VAN-042');
    expect(await screen.findByTestId('tel-push-result')).toHaveTextContent('Stored as fleet / VAN-042');
  });
  it('says plainly when it arrived but the mapping did not store it', async () => {
    apiReply = () => ({ data: { stored: false, message: 'No asset in the message. Set the asset in the mapping.' }, error: null });
    render(<PushPanel sourceId="src-1" token={null} />);
    await act(async () => { fireEvent.click(screen.getByTestId('tel-push-test')); });
    expect(await screen.findByTestId('tel-push-result')).toHaveTextContent('No asset in the message');
  });
});

describe('capture a live message gives up with a reason (W2)', () => {
  it('shows the countdown, then the reason with Retry', async () => {
    let resolve: (v: unknown) => void = () => {};
    apiReply = (path, init) => {
      if (init && JSON.parse(init.body).capture) return new Promise((r) => { resolve = r; });
      return { data: { records: [], errors: [] }, error: null };
    };
    render(<MappingEditor sourceId="s1" decoder="json" mapping={BLANK_MAPPING} onChange={() => {}} />);
    await act(async () => { fireEvent.click(screen.getByTestId('tel-map-capture')); });
    expect(screen.getByTestId('tel-map-capturing')).toHaveTextContent('20 s');
    expect(screen.getByTestId('tel-map-capture-cancel')).toBeInTheDocument();
    await act(async () => { resolve({ data: null, error: 'x', errorDetail: { code: 409, error_code: 'SIGN_IN_FAILED', message: 'x' } }); });
    expect(await screen.findByTestId('tel-map-capture-error')).toHaveTextContent('refused the sign-in');
    expect(screen.getByTestId('tel-map-capture-retry')).toBeInTheDocument();
  });
  it('cancel stops waiting at once', async () => {
    apiReply = (path, init) => (init && JSON.parse(init.body).capture ? new Promise(() => {}) : { data: null, error: null });
    render(<MappingEditor sourceId="s1" decoder="json" mapping={BLANK_MAPPING} onChange={() => {}} />);
    await act(async () => { fireEvent.click(screen.getByTestId('tel-map-capture')); });
    await act(async () => { fireEvent.click(screen.getByTestId('tel-map-capture-cancel')); });
    await waitFor(() => expect(screen.getByTestId('tel-map-capture')).toBeInTheDocument());
    expect(screen.queryByTestId('tel-map-capture-error')).toBeNull();
  });
  it('names each reason', () => {
    expect(captureReason({ code: 'SOURCE_OFF' })).toMatch(/turned off/);
    expect(captureReason({ code: 'CANNOT_CONNECT' })).toMatch(/cannot connect/);
    expect(captureReason({ code: 'NOTHING_ARRIVED' })).toMatch(/Nothing arrived in 20 seconds/);
    expect(captureReason({ status: 408 })).toMatch(/Nothing arrived/);
  });
});

describe('testbed details (W1)', () => {
  const tb = {
    installed: true,
    services: [
      { name: 'Kafka (Redpanda)', transport: 'kafka', address: 'redpanda:9092', config: { bootstrap_servers: 'redpanda:9092', security_protocol: 'SASL_PLAINTEXT', sasl_mechanism: 'SCRAM-SHA-256', username: 'abenix' }, secrets: { password: 'pw' }, subjects: ['plant.telemetry'] },
      { name: 'RabbitMQ', transport: 'amqp', reachable: true },
    ],
  };
  it('finds the service for a kind and fills the form', () => {
    const svc = testbedServiceFor(tb, 'kafka')!;
    expect(svc.name).toBe('Kafka (Redpanda)');
    const v = testbedValues(svc, { client_id: 'abenix' });
    expect(v).toMatchObject({ bootstrap_servers: 'redpanda:9092', username: 'abenix', password: 'pw', sasl_mechanism: 'SCRAM-SHA-256', subjects: 'plant.telemetry', client_id: 'abenix' });
    expect(testbedSummary(svc)).toContain('user abenix');
    expect(testbedSummary(svc)).not.toContain('pw');
  });
  it('offers nothing when the testbed is missing or the service has no details', () => {
    expect(testbedServiceFor({ installed: false, services: tb.services }, 'kafka')).toBeNull();
    expect(testbedServiceFor(tb, 'amqp')).toBeNull();
    expect(testbedServiceFor(null, 'kafka')).toBeNull();
  });
});

describe('Kafka form hints (polish)', () => {
  const f = (over: Partial<FieldDecl>): FieldDecl => ({ key: 'x', kind: 'string', ...over } as FieldDecl);
  it('says the example once', () => {
    const h = fieldHelp(f({ key: 'username', description: 'The SASL user. Leave empty for PLAINTEXT or SSL. Example: abenix' }));
    expect(h.help).toBe('The SASL user. Leave empty for PLAINTEXT or SSL.');
    expect(h.example).toBe('abenix');
  });
  it('leaves the separator to one list hint', () => {
    const h = fieldHelp(f({ key: 'subjects', kind: 'list', description: 'The topics to read, comma or newline separated. Example: shop.orders' }));
    expect(h.help).toBe('The topics to read.');
    expect(h.example).toBe('shop.orders');
    expect(LIST_HINT).toBe('One per line, or separated by commas.');
  });
  it('hides OAuth and TLS until the protocol needs them', () => {
    const k = (key: string, values: Record<string, unknown>) => fieldShown('kafka', f({ key }), values);
    expect(k('oauth_token_url', { security_protocol: 'SASL_SSL', sasl_mechanism: 'PLAIN' })).toBe(false);
    expect(k('oauth_token_url', { security_protocol: 'SASL_SSL', sasl_mechanism: 'OAUTHBEARER' })).toBe(true);
    expect(k('password', { security_protocol: 'PLAINTEXT' })).toBe(false);
    expect(k('password', { security_protocol: 'SASL_PLAINTEXT', sasl_mechanism: 'SCRAM-SHA-256' })).toBe(true);
    expect(k('tls_ca', { security_protocol: 'SASL_PLAINTEXT' })).toBe(false);
    expect(k('tls_ca', { security_protocol: 'SSL' })).toBe(true);
    expect(k('bootstrap_servers', {})).toBe(true);
    expect(fieldShown('mqtt', f({ key: 'tls_ca' }), { broker_url: 'mqtt://b:1883' })).toBe(false);
    expect(fieldShown('mqtt', f({ key: 'tls_ca' }), { broker_url: 'mqtts://b:8883' })).toBe(true);
  });
});

describe('asset cards at phone width (gap 4)', () => {
  it('measures a grid that mounts after loading, one column at 390', async () => {
    const { useWidth, columnsFor } = await import('@/components/telemetry/DevicesTab');
    const { useState } = await import('react');
    function Probe() {
      const [show, setShow] = useState(false);
      const [ref, w] = useWidth<HTMLDivElement>();
      return (
        <>
          <button onClick={() => setShow(true)}>show</button>
          {show && <div ref={(el) => { if (el) Object.defineProperty(el, 'clientWidth', { configurable: true, value: 358 }); ref(el); }} />}
          <p data-testid="cols">{w ? columnsFor(w) : 'none'}</p>
        </>
      );
    }
    render(<Probe />);
    expect(screen.getByTestId('cols')).toHaveTextContent('none');
    await act(async () => { fireEvent.click(screen.getByText('show')); });
    expect(screen.getByTestId('cols')).toHaveTextContent('1');
  });
});

describe('asset labels when names repeat (gap 9)', () => {
  it('adds the group only when a name is in two groups', async () => {
    const { assetLabel, repeatedNames, agentAssetLabel } = await import('@/lib/telemetry/assetLabel');
    const list = [{ group: 'energy', node: 'meter-1' }, { group: 'plant', node: 'meter-1' }, { group: 'plant', node: 'pump-7', display_name: 'Pump 7' }];
    const rep = repeatedNames(list);
    expect(assetLabel(list[0], rep)).toBe('energy/meter-1');
    expect(assetLabel(list[2], rep)).toBe('Pump 7 (pump-7)');
    expect(assetLabel({ group: 'a', node: 'x' }, rep)).toBe('x');
    expect(agentAssetLabel('energy/meter-1', 'meter-1')).toBe('energy/meter-1');
    expect(agentAssetLabel('energy/meter-1', 'Main meter')).toBe('Main meter (energy/meter-1)');
  });
});

describe('edge register lines checked on blur (gap 12)', () => {
  it('shows only the field that lost focus, and keeps typing quiet for the rest', async () => {
    const { blurCheck, keepShown, fieldKeyOf } = await import('@/components/edge/model');
    const all = { registers: 'Line 1: x is not a number', 'asset.group': 'Needed' };
    expect(blurCheck(all, undefined, 'registers')).toEqual({ registers: 'Line 1: x is not a number' });
    expect(blurCheck({}, { registers: 'old' }, 'registers')).toEqual({});
    expect(keepShown(all, { registers: 'old' })).toEqual({ registers: 'Line 1: x is not a number' });
    expect(fieldKeyOf('edge-c0-registers', 'edge-c0')).toBe('registers');
    expect(fieldKeyOf('edge-c0-asset-group', 'edge-c0')).toBe('asset.group');
    expect(fieldKeyOf('edge-c0-interval', 'edge-c0')).toBe('interval_s');
  });
});

describe('register map lines', () => {
  it('names the first line that will not work', async () => {
    const { registerLinesProblem } = await import('@/components/edge/model');
    expect(registerLinesProblem('voltage_v, holding, 0, float32, 1, V\nbreaker_closed, coil, 0')).toBeNull();
    expect(registerLinesProblem('voltage_v, holding, x, float32, 1, V')).toMatch(/Line 1: the address "x" must be a whole number/);
    expect(registerLinesProblem('ok, holding, 0\npower, coils, 3')).toMatch(/Line 2: the table "coils"/);
    expect(registerLinesProblem('a, holding, 0, float99')).toMatch(/the type "float99"/);
  });
});
