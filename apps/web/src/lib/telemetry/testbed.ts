export interface TestbedService {
  name: string;
  transport?: string;
  address?: string;
  reachable?: boolean;
  config?: Record<string, unknown>;
  secrets?: Record<string, unknown>;
  subjects?: string[];
  decoder?: string;
}

export interface TestbedInfo { installed?: boolean; services?: TestbedService[] }

// the testbed service a new source of this kind can copy, only when the server sent its details
export function testbedServiceFor(tb: TestbedInfo | null | undefined, transport: string): TestbedService | null {
  if (!tb?.installed || !transport) return null;
  const svc = (tb.services || []).find((s) => s.transport === transport);
  if (!svc || (!svc.config && !svc.secrets && !svc.address)) return null;
  return svc;
}

// form values from a testbed service, its config, secrets and subjects merged over what is there
export function testbedValues(svc: TestbedService, current: Record<string, unknown> = {}): Record<string, unknown> {
  const out: Record<string, unknown> = { ...current };
  for (const [k, v] of Object.entries(svc.config || {})) if (v !== undefined && v !== null) out[k] = v;
  for (const [k, v] of Object.entries(svc.secrets || {})) if (v !== undefined && v !== null && v !== '') out[k] = v;
  if (svc.subjects?.length) out.subjects = svc.subjects.join(', ');
  if (!svc.config && svc.address) {
    if (svc.transport === 'kafka') out.bootstrap_servers = svc.address;
    else if (svc.transport === 'opcua') out.endpoint = `opc.tcp://${svc.address}`;
  }
  return out;
}

// what was filled in, in words, secrets never shown
export function testbedSummary(svc: TestbedService): string {
  const c = svc.config || {};
  const bits: string[] = [];
  const addr = (c.bootstrap_servers || c.broker_url || c.url || c.endpoint || c.host || svc.address) as string | undefined;
  if (addr) bits.push(`address ${addr}${c.port && !String(addr).includes(':') ? `:${c.port}` : ''}`);
  if (c.username) bits.push(`user ${c.username}`);
  if (c.sasl_mechanism) bits.push(String(c.sasl_mechanism));
  if (svc.secrets && Object.keys(svc.secrets).length) bits.push('password set');
  if (svc.subjects?.length) bits.push(`${svc.subjects.length === 1 ? 'topic' : 'topics'} ${svc.subjects.join(', ')}`);
  return bits.join(', ');
}
