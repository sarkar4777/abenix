import { describe, expect, it } from 'vitest';
import { brokerUrlProblem, describeTest, explainTelemetryError, isPlain, nameProblem, reasonProblem, topicsProblem } from '@/lib/telemetry/errors';
import { commandPreview, parseValue } from '@/lib/telemetry/command';

const RAW = /\b[A-Z]+(?:_[A-Z]+)+\b|HTTP \d{3}|Server error|\{|undefined|null/;

describe('plain-language errors', () => {
  it('says why a command was not sent when the machine is offline', () => {
    const t = explainTelemetryError({ status: 409, errorCode: 'NODE_OFFLINE', message: 'node offline' }, 'command', { node: 'ipc-ex1', device: 'safety' });
    expect(t).toBe('ipc-ex1/safety is offline, so nothing was sent. Commands go through once it is back online and has sent its birth message.');
  });
  it('names the permission and where to get it', () => {
    expect(explainTelemetryError({ status: 403 }, 'command')).toMatch(/Send machine commands permission \(telemetry\.command\)\. An admin can grant it under Admin, Permissions/);
    expect(explainTelemetryError({ status: 403 }, 'save')).toMatch(/needs Manage telemetry brokers/);
    expect(explainTelemetryError({ status: 403 }, 'load')).toMatch(/not shared with you or your team/);
  });
  it('maps rate limits, quotas, missing servers and network failures', () => {
    expect(explainTelemetryError({ status: 429 }, 'command')).toMatch(/^Too many commands to this machine in one second/);
    expect(explainTelemetryError({ status: 400, errorCode: 'QUOTA_EXCEEDED', message: 'quota_exceeded: max_connections=3' }, 'save')).toMatch(/reached its telemetry limit/);
    expect(explainTelemetryError({ status: 404 }, 'load')).toMatch(/not switched on for this server yet/);
    expect(explainTelemetryError({ status: 0, errorCode: 'NETWORK_ERROR' }, 'load')).toMatch(/Could not reach Abenix/);
  });
  it('keeps a server message only when it reads as a sentence', () => {
    expect(explainTelemetryError({ status: 422, message: 'A connection called Site broker already exists.' }, 'save')).toBe('A connection called Site broker already exists.');
    expect(explainTelemetryError({ status: 422, message: "{'loc': ['body','broker_url']}" }, 'save')).toMatch(/Check the fields marked in red/);
    expect(explainTelemetryError({ status: 500, message: 'Server error (500)' }, 'command')).toMatch(/hit a problem sending the command/);
    expect(isPlain('INVALID_TOPIC_FILTER in subscribe.')).toBe(false);
  });
  it('never shows a raw code or JSON for any status', () => {
    for (const status of [0, 400, 401, 403, 404, 409, 422, 429, 500, 503]) {
      for (const action of ['load', 'save', 'test', 'command', 'delete'] as const) {
        expect(explainTelemetryError({ status, errorCode: 'SOME_CODE_ERROR', message: '{"detail":"x"}' }, action)).not.toMatch(RAW);
      }
    }
  });
});

describe('connection test result', () => {
  const url = 'mqtt://abenix-mosquitto:1883';
  it('says how many messages came in', () => {
    expect(describeTest({ ok: true, connected: true, messages: 128, topics_seen: ['a', 'b', 'c'], error: null }, url).text).toBe('Connected to abenix-mosquitto:1883. 128 messages arrived in 5 seconds on 3 topics.');
  });
  it('says connected but quiet, and what to check', () => {
    expect(describeTest({ ok: true, connected: true, messages: 0, topics_seen: [], error: null }, url).text).toMatch(/but no messages arrived in 5 seconds/);
  });
  it('turns broker errors into plain words', () => {
    const t = (error: string) => describeTest({ ok: false, connected: false, messages: 0, topics_seen: [], error }, url).text;
    expect(t('[Errno -2] Name or service not known')).toBe('The address abenix-mosquitto:1883 could not be found. Check the spelling of the host name.');
    expect(t('Connection refused')).toMatch(/refused the connection/);
    expect(t('Not authorized')).toMatch(/refused the username or password/);
    expect(t('timed out')).toMatch(/did not answer within 5 seconds/);
    expect(t('Could not reach the broker at abenix-mosquitto:1883. Check the address and that the broker is running.')).toBe('Could not reach the broker at abenix-mosquitto:1883. Check the address and that the broker is running.');
  });
});

describe('field checks', () => {
  it('checks the broker address', () => {
    expect(brokerUrlProblem('')).toMatch(/Enter the broker address/);
    expect(brokerUrlProblem('tcp://x:1883')).toMatch(/Start the address with mqtt:\/\//);
    expect(brokerUrlProblem('mqtt://broker')).toBe('Add the port, usually 1883, for example mqtt://broker:1883.');
    expect(brokerUrlProblem('mqtts://broker')).toMatch(/usually 8883/);
    expect(brokerUrlProblem('mqtt://broker:99999')).toMatch(/1 to 65535/);
    expect(brokerUrlProblem('mqtt://abenix-mosquitto.abenix.svc.cluster.local:1883')).toBeNull();
  });
  it('checks topic filters', () => {
    expect(topicsProblem([], true)).toMatch(/at least one topic/);
    expect(topicsProblem([], false)).toBeNull();
    expect(topicsProblem(['spBv1.0/#/x'], true)).toMatch(/# must be a level of its own at the end/);
    expect(topicsProblem(['groundwork/a+/can'], true)).toMatch(/\+ must be a whole level/);
    expect(topicsProblem(['spBv1.0/#', 'groundwork/+/can/raw'], true)).toBeNull();
  });
  it('checks names and reasons', () => {
    expect(nameProblem(' site broker ', ['Site broker'])).toMatch(/already has this name/);
    expect(reasonProblem('ok')).toMatch(/at least 5 characters/);
    expect(reasonProblem('worker in zone')).toBeNull();
  });
});

describe('commands', () => {
  it('previews the exact DCMD, or NCMD for the node itself', () => {
    const p = commandPreview({ group: 'groundwork', node: 'ipc-ex1', device: 'safety', metric: 'Safety/Hold', datatype: 'Boolean', value: true }, 1000);
    expect(p.kind).toBe('DCMD');
    expect(p.topic).toBe('spBv1.0/groundwork/DCMD/ipc-ex1/safety');
    expect(JSON.parse(p.payload)).toEqual({ timestamp: 1000, metrics: [{ name: 'Safety/Hold', timestamp: 1000, datatype: 'Boolean', value: true }] });
    expect(commandPreview({ group: 'g', node: 'n', device: '', metric: 'Node Control/Rebirth', datatype: 'Boolean', value: true }).topic).toBe('spBv1.0/g/NCMD/n');
  });
  it('checks the value against its type', () => {
    expect(parseValue('boolean', 'true')).toEqual({ value: true, problem: null });
    expect(parseValue('integer', '2.5').problem).toMatch(/whole numbers/);
    expect(parseValue('number', 'abc').problem).toMatch(/is not a number/);
    expect(parseValue('json', '{"task":"dig"}')).toEqual({ value: '{"task":"dig"}', problem: null });
    expect(parseValue('json', '{task}').problem).toMatch(/not valid JSON/);
    expect(parseValue('choice', 'safe', [{ value: 'auto' }, { value: 'safe' }])).toEqual({ value: 'safe', problem: null });
  });
});

describe('server wording', () => {
  it('keeps a plain refusal from the server word for word', () => {
    const msg = 'ipc-ex1 is offline since 2026-10-11 14:02:11 UTC, so the command was not sent.';
    expect(explainTelemetryError({ status: 409, errorCode: 'NODE_OFFLINE', message: msg }, 'command', { node: 'ipc-ex1' })).toBe(msg);
    expect(explainTelemetryError({ status: 502, errorCode: 'BROKER_UNREACHABLE', message: '[Errno 111] Connection refused' }, 'command')).toMatch(/could not reach the broker to send this/);
  });
});
