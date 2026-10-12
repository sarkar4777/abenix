import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

import DevicesTab from '@/components/telemetry/DevicesTab';
import { emptyBatch } from '@/lib/telemetry/stream';
import { sortedNodes, useTelemetry } from '@/lib/telemetry/store';
import type { DeviceRow } from '@/lib/telemetry/types';

// 1,000 nodes with 5 devices each, the 5,000 device case
function fleet(): DeviceRow[] {
  const rows: DeviceRow[] = [];
  for (let i = 0; i < 1000; i++) {
    const node = `ipc-${String(i).padStart(4, '0')}`;
    const group = `site-${i % 10}`;
    rows.push({ group, node, device: '', online: true, last_seen: Date.now(), birth_at: 1, msgs_per_sec: 400, seq_gaps: 0, metric_count: 12 });
    for (const d of ['engine', 'telematics', 'safety', 'hydraulics', 'swing']) {
      rows.push({ group, node, device: d, online: i % 97 !== 0, last_seen: Date.now(), birth_at: 1, msgs_per_sec: 80, seq_gaps: 0, metric_count: 20, team_name: i % 2 ? 'North' : 'South' });
    }
  }
  return rows;
}

const base = {
  loaded: true, error: null, onRetry: () => {}, setFilter: () => {}, setView: () => {}, connections: [], canManage: true, openConnections: () => {}, onFirst: () => {}, total: 5000,
};

describe('5,000 devices', () => {
  beforeEach(() => {
    useTelemetry.getState().reset();
    (globalThis as any).ResizeObserver = class { observe() {} disconnect() {} unobserve() {} };
  });
  afterEach(() => {
    delete (globalThis as any).ResizeObserver;
  });

  it('builds, filters and sorts the fleet well inside one frame budget each', () => {
    const rows = fleet();
    let t = performance.now();
    useTelemetry.getState().setRows(rows);
    const build = performance.now() - t;
    const nodes = useTelemetry.getState().nodes;
    t = performance.now();
    const north = sortedNodes(nodes, { q: 'ipc-09', group: '', status: '', team: 'North' });
    const filter = performance.now() - t;
    expect(Object.keys(nodes)).toHaveLength(1000);
    expect(north.length).toBe(50);
    expect(build).toBeLessThan(250);
    expect(filter).toBeLessThan(50);
  });

  it('renders only the cards on screen and stays bounded as live updates land', () => {
    useTelemetry.getState().setRows(fleet());
    const onVisible = vi.fn();
    const t0 = performance.now();
    const { rerender } = render(
      <DevicesTab {...base} nodes={useTelemetry.getState().nodes} filter={{ q: '', group: '', status: '', team: '' }} view="cards" onVisible={onVisible} now={Date.now()} />,
    );
    const first = performance.now() - t0;
    const cards = screen.queryAllByTestId('tel-node-card').length;
    expect(screen.getByTestId('tel-grid-windowed')).toBeInTheDocument();
    expect(cards).toBeGreaterThan(0);
    expect(cards).toBeLessThan(80);
    expect(screen.getByTestId('tel-count')).toHaveTextContent('1000 of 1000 assets');

    // a tick of 10 Hz deltas for every device in the fleet
    const b = emptyBatch();
    for (const r of fleet()) b.devices.set(`${r.group}/${r.node}/${r.device}`, { group: r.group, node: r.node, device: r.device, msgs_per_sec: 90 });
    const ticks: number[] = [];
    for (let i = 0; i < 5; i++) {
      const t = performance.now();
      act(() => useTelemetry.getState().applyBatch(b));
      rerender(<DevicesTab {...base} nodes={useTelemetry.getState().nodes} filter={{ q: '', group: '', status: '', team: '' }} view="cards" onVisible={onVisible} now={Date.now()} />);
      ticks.push(performance.now() - t);
    }
    expect(screen.queryAllByTestId('tel-node-card').length).toBe(cards);
    // jsdom is several times slower than a browser, these bounds catch an unwindowed list
    expect(first).toBeLessThan(3000);
    expect(Math.max(...ticks)).toBeLessThan(800);
  });

  it('windows the device table too', () => {
    useTelemetry.getState().setRows(fleet());
    render(<DevicesTab {...base} nodes={useTelemetry.getState().nodes} filter={{ q: '', group: '', status: '', team: '' }} view="table" onVisible={() => {}} now={Date.now()} />);
    expect(screen.getByTestId('tel-count')).toHaveTextContent('5000 parts');
    const rows = screen.queryAllByTestId('tel-device-row').length;
    expect(rows).toBeGreaterThan(0);
    expect(rows).toBeLessThan(80);
  });
});
