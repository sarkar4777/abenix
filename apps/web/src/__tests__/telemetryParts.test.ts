import { describe, expect, it, vi } from 'vitest';

vi.mock('next/link', () => ({ default: () => null }));

import { partSummaries } from '@/components/telemetry/PartsOverview';
import { buildNodes } from '@/lib/telemetry/store';

const row = (device: string, extra: Record<string, unknown> = {}) => ({ group: 'edge-demo', node: 'truck-7', device, online: true, last_seen: 1760000000000, birth_at: 1, msgs_per_sec: 0.4, readings_per_sec: 11, seq_gaps: 0, metric_count: 0, ...extra });

describe('whole asset made of parts', () => {
  const nodes = buildNodes([row(''), row('engine'), row('gps'), row('bus', { online: false, readings_per_sec: 0, msgs_per_sec: 0 })] as never);
  const entry = nodes['edge-demo/truck-7'];
  const metrics = {
    'edge-demo/truck-7/engine': {
      'Engine/Speed_rpm': { name: 'Engine/Speed_rpm', value: 1350 },
      'Engine/CoolantTemp_C': { name: 'Engine/CoolantTemp_C', value: 88 },
      'ECU/Address': { name: 'ECU/Address', value: 0 },
    },
    'edge-demo/truck-7/gps': { 'GPS/Speed_kmh': { name: 'GPS/Speed_kmh', value: 42 }, 'GPS/Lat': { name: 'GPS/Lat', value: 51.5 } },
  };

  it('lists every part with status, readings a second and its headline values', () => {
    const parts = partSummaries(entry, metrics, {}, 2);
    expect(parts.map((p) => p.device)).toEqual(['bus', 'engine', 'gps']);
    const engine = parts.find((p) => p.device === 'engine')!;
    expect(engine.online).toBe(true);
    expect(engine.rate).toEqual({ value: '11', unit: 'readings/s' });
    expect(engine.headline.map((m) => m.name)).toEqual(['Engine/Speed_rpm', 'Engine/CoolantTemp_C']);
    expect(parts.find((p) => p.device === 'gps')!.headline.map((m) => m.name)).toEqual(['GPS/Speed_kmh', 'GPS/Lat']);
  });

  it('shows an offline part with no values plainly, not as a reporting one', () => {
    const bus = partSummaries(entry, metrics, {}, 2).find((p) => p.device === 'bus')!;
    expect(bus.online).toBe(false);
    expect(bus.headline).toEqual([]);
    expect(bus.rate.value).toBe('0');
  });

  it('gives nothing for an asset with no parts', () => {
    expect(partSummaries(undefined, {}, {})).toEqual([]);
  });
});
