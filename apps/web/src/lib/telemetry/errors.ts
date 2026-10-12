import type { Connection, ConnectionTest } from './types';

export type TelemetryAction = 'load' | 'save' | 'test' | 'toggle' | 'delete' | 'command' | 'history' | 'frames' | 'share';

export interface ErrLike { status?: number; code?: string | null; message?: string | null }

export function errLike(e: unknown): ErrLike {
  if (!e || typeof e !== 'object') return { message: typeof e === 'string' ? e : null };
  const o = e as Record<string, unknown>;
  return {
    status: typeof o.status === 'number' ? o.status : typeof o.code === 'number' ? (o.code as number) : undefined,
    code: (o.errorCode ?? o.error_code ?? (typeof o.code === 'string' ? o.code : null)) as string | null,
    message: typeof o.message === 'string' ? o.message : null,
  };
}

// a server message is shown as is only when it already reads as a sentence
export function isPlain(msg: string | null | undefined): msg is string {
  if (!msg) return false;
  const m = msg.trim();
  if (m.length < 12 || m.length > 260) return false;
  if (/[{}[\]<>]|Traceback|Exception|\bat \S+:\d+|errno|\bNone\b|\bnull\b|undefined|Server error \(\d+\)|HTTP \d{3}/i.test(m)) return false;
  if (/\b[A-Z]{2,}(?:_[A-Z]+)+\b/.test(m)) return false;
  return /^[A-Za-z0-9]/.test(m) && /[.!?]$/.test(m);
}

const CAN_MANAGE = 'Changing broker connections needs Manage telemetry brokers, which admins have. Ask an admin to make the change.';
const CAN_COMMAND = 'Sending commands needs the Send machine commands permission (telemetry.command). An admin can grant it under Admin, Permissions, for example with the Machine operators set.';

export function explainTelemetryError(e: unknown, action: TelemetryAction, ctx: { node?: string; device?: string } = {}): string {
  const { status, code, message } = errLike(e);
  const c = (code || '').toUpperCase();
  const msg = message || '';
  if (c === 'NETWORK_ERROR' || status === 0) return 'Could not reach Abenix. Check your network connection, then try again.';
  if (c === 'SERVER_BUSY' || c === 'BUSY' || (!c && (status === 502 || status === 503 || status === 504))) {
    return ['load', 'history', 'frames'].includes(action)
      ? 'Abenix is busy right now. Retrying on its own, or press Try again.'
      : 'Abenix is busy right now and this did not go through. Try again in a moment.';
  }
  if (c === 'SESSION_EXPIRED' || c === 'NO_TOKEN' || status === 401) return 'Your session has ended. Sign in again to carry on.';
  if (c === 'BROKER_UNREACHABLE') return 'Abenix could not reach the broker to send this. Check the connection on the Connections tab, then try again.';
  if (c === 'HISTORY_UNAVAILABLE') return 'Stored history is not available right now, so the chart shows only the live values since you opened this page. Try again in a minute.';
  // the server already says it plainly, keep its words
  if (isPlain(msg) && status !== 500) return msg;
  if (c === 'QUOTA_EXCEEDED' || /quota|limit of \d+/i.test(msg)) {
    return isPlain(msg) ? msg : 'Your workspace has reached its telemetry limit. An admin can raise it in Admin, Settings, or remove a connection you no longer use.';
  }
  const who = ctx.device ? `${ctx.node}/${ctx.device}` : ctx.node || 'The machine';
  if (c === 'NODE_OFFLINE' || (action === 'command' && /offline|not connected|no birth/i.test(msg))) {
    return `${who} is offline, so nothing was sent. Commands go through once it is back online and has sent its birth message.`;
  }
  if (c === 'RATE_LIMITED' || status === 429) {
    return action === 'command'
      ? 'Too many commands to this machine in one second. Wait a moment and send it again.'
      : 'Too many requests in a short time. Wait a moment and try again.';
  }
  if (c === 'FORBIDDEN' || status === 403) {
    if (action === 'command') return CAN_COMMAND;
    if (action === 'load' || action === 'history' || action === 'frames') return 'This is not shared with you or your team. Ask the admin who manages the connection to share it.';
    return CAN_MANAGE;
  }
  if (status === 404) {
    if (action === 'load') return 'Telemetry is not switched on for this server yet. An admin can update Abenix to 2.5.8 or later and run the deploy again.';
    if (action === 'command') return `${who} is not known to Abenix. It shows up once it sends its birth message.`;
    return 'That connection no longer exists. Someone may have deleted it. Refresh the page to see the current list.';
  }
  if (status === 400 || status === 409 || status === 422 || c === 'VALIDATION_ERROR') {
    return isPlain(msg) ? msg : 'Some of the details are not valid. Check the fields marked in red and try again.';
  }
  if (isPlain(msg)) return msg;
  const what = { load: 'loading telemetry', save: 'saving the connection', test: 'testing the connection', toggle: 'changing the connection', delete: 'deleting the connection', command: 'sending the command', history: 'loading the history', frames: 'loading the frames', share: 'sharing the connection' }[action];
  return `Abenix hit a problem ${what}. Try again in a moment, and if it keeps happening an admin can check the Alerts page.`;
}

export function hostOf(url: string): string {
  const m = /^[a-z]+:\/\/(?:[^@/]*@)?([^/?#]+)/i.exec(url.trim());
  return m ? m[1] : url;
}

// the test result in one or two plain sentences
const TLS_HINT: Record<string, string> = {
  kafka: 'Check the security protocol is SSL or SASL_SSL, the port is the TLS listener and the broker certificate is valid.',
  mqtt: 'Check the broker takes mqtts on this port and has a valid certificate.',
  amqp: 'Check the broker takes amqps on this port and has a valid certificate.',
  nats: 'Check the server has TLS switched on for this port and a valid certificate.',
  opcua: 'Check the security policy and mode match the server, and that the server trusts the client certificate.',
  websocket: 'Check the address starts with wss:// and the server certificate is valid.',
};

function transportFamily(transport?: string | null): string {
  const t = (transport || '').toLowerCase();
  if (t.startsWith('kafka')) return 'kafka';
  if (t.startsWith('mqtt') || t.startsWith('sparkplug')) return 'mqtt';
  if (t.startsWith('amqp') || t.startsWith('rabbit')) return 'amqp';
  if (t.startsWith('nats')) return 'nats';
  if (t.startsWith('opc')) return 'opcua';
  if (t.startsWith('ws') || t.startsWith('websocket')) return 'websocket';
  return t;
}

export function describeTest(t: ConnectionTest, brokerUrl: string, transport?: string | null): { ok: boolean; text: string } {
  const host = hostOf(brokerUrl);
  const fam = transportFamily(transport || (/^mqtts?:/i.test(brokerUrl) ? 'mqtt' : ''));
  if (t.connected || t.ok) {
    const topics = t.topics_seen?.length ?? 0;
    if (t.messages > 0) {
      return { ok: true, text: `Connected to ${host}. ${t.messages} message${t.messages === 1 ? '' : 's'} arrived in 5 seconds on ${topics} topic${topics === 1 ? '' : 's'}.` };
    }
    const widen = fam === 'mqtt' ? ', or widen them, for example to spBv1.0/#' : fam === 'nats' ? ', or widen them, for example to plant.>' : '';
    return { ok: true, text: `Connected to ${host}, but no messages arrived in 5 seconds. Check that a machine is publishing on the ${fam === 'nats' ? 'subjects' : 'topics'} listed${widen}.` };
  }
  const e = t.error || '';
  if (isPlain(e)) return { ok: false, text: e };
  if (/not authori[sz]ed|bad user ?name|password|auth/i.test(e)) return { ok: false, text: `The broker at ${host} refused the username or password. Check them and save again.` };
  if (/tls|ssl|certificate|handshake/i.test(e)) return { ok: false, text: `The secure connection to ${host} failed. ${TLS_HINT[fam] ?? 'Check the port is the secure one and the server certificate is valid.'}` };
  if (/getaddrinfo|name or service|resolve|nodename|unknown host/i.test(e)) return { ok: false, text: `The address ${host} could not be found. Check the spelling of the host name.` };
  if (/refused/i.test(e)) return { ok: false, text: `The broker at ${host} refused the connection. Check the port and that the broker is running.` };
  if (/time ?out|timed out/i.test(e)) return { ok: false, text: `The broker at ${host} did not answer within 5 seconds. Check the address, the port and any firewall in between.` };
  return { ok: false, text: `Could not reach the broker at ${host}. Check the address and that the broker is running.` };
}

export function statusText(c: Pick<Connection, 'status' | 'enabled'>): { label: string; tone: 'ok' | 'wait' | 'bad' | 'off' } {
  if (!c.enabled || c.status === 'disabled') return { label: 'Turned off', tone: 'off' };
  if (c.status === 'connected') return { label: 'Connected', tone: 'ok' };
  if (c.status === 'error') return { label: 'Cannot connect', tone: 'bad' };
  return { label: 'Connecting', tone: 'wait' };
}

export const EXAMPLE_BROKER = 'mqtt://abenix-mosquitto.abenix.svc.cluster.local:1883';

export function brokerUrlProblem(raw: string): string | null {
  const v = raw.trim();
  if (!v) return 'Enter the broker address, for example mqtt://abenix-mosquitto.abenix.svc.cluster.local:1883.';
  if (/\s/.test(v)) return 'The address cannot contain spaces.';
  const m = /^(mqtts?):\/\/([^/:?#\s]+)(?::(\d+))?\/?$/i.exec(v);
  if (!m) {
    if (!/^mqtts?:\/\//i.test(v)) return 'Start the address with mqtt:// or, for a secure connection, mqtts://.';
    return 'Use the form mqtt://host:port with no path after the port.';
  }
  if (m[3] !== undefined) {
    const port = Number(m[3]);
    if (!(port >= 1 && port <= 65535)) return 'The port must be a number from 1 to 65535.';
  } else {
    return `Add the port, usually ${m[1].toLowerCase() === 'mqtts' ? '8883' : '1883'}, for example ${m[1].toLowerCase()}://${m[2]}:${m[1].toLowerCase() === 'mqtts' ? '8883' : '1883'}.`;
  }
  return null;
}

export function splitTopics(raw: string): string[] {
  return raw.split(/[\n,]+/).map((t) => t.trim()).filter(Boolean);
}

export function topicsProblem(topics: string[], required: boolean): string | null {
  if (!topics.length) return required ? 'Add at least one topic. spBv1.0/# takes every Sparkplug B message.' : null;
  for (const t of topics) {
    if (/\s/.test(t)) return `"${t}" has a space in it. Topics cannot contain spaces.`;
    const levels = t.split('/');
    if (levels.some((l, i) => l.includes('#') && (l !== '#' || i !== levels.length - 1))) return `In "${t}", # must be a level of its own at the end, like spBv1.0/#.`;
    if (levels.some((l) => l.includes('+') && l !== '+')) return `In "${t}", + must be a whole level, like groundwork/+/can/raw.`;
  }
  return null;
}

export function nameProblem(raw: string, taken: string[]): string | null {
  const v = raw.trim();
  if (!v) return 'Give the connection a name people will recognise, such as Site broker.';
  if (v.length > 80) return 'Keep the name under 80 characters.';
  if (taken.some((t) => t.trim().toLowerCase() === v.toLowerCase())) return 'Another connection already has this name. Pick a different one.';
  return null;
}

export const REASON_MIN = 5;

export function reasonProblem(raw: string): string | null {
  if (raw.trim().length < REASON_MIN) return `Say why you are sending this, at least ${REASON_MIN} characters. It goes on the audit log with your name.`;
  return null;
}

export const CAPTURE_SECONDS = 20;

// why a live capture came back empty, in the words of what to do next
export function captureReason(e: unknown): string {
  const { status, code, message } = errLike(e);
  const c = (code || '').toUpperCase();
  if (c === 'SOURCE_OFF' || c === 'SOURCE_DISABLED') return 'The source is turned off, so nothing can arrive. Turn it on under Sources, then try again.';
  if (c === 'CANNOT_CONNECT' || c === 'BROKER_UNREACHABLE') return `Abenix cannot connect to the source.${isPlain(message) ? ` ${message}` : ''} Check its address and port in the settings, then try again.`;
  if (c === 'SIGN_IN_FAILED' || c === 'AUTH_FAILED') return 'The source refused the sign-in. Check the user name, password and sign-in method in the settings, then try again.';
  if (c === 'NOTHING_ARRIVED' || c === 'CAPTURE_TIMEOUT' || status === 408) return `Nothing arrived in ${CAPTURE_SECONDS} seconds. Check that something is sending on the topics this source reads, then try again.`;
  return explainTelemetryError(e, 'load');
}
