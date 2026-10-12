import { render, screen } from '@testing-library/react';
import CommandApproval from '@/components/approvals/CommandApproval';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn(async () => ({ data: null, error: null })) }));

const T0 = Date.UTC(2026, 9, 12, 9, 0);
const oil = [0, 1, 2, 3].map((i) => ({ t: T0 + i * 60_000, avg: 70 + i * 2, min: 69 + i * 2, max: 71 + i * 2 }));

const base = {
  command: { group: 'groundwork', node: 'ipc-ex1', device: 'safety', signal: 'Mode/Set', value: 'safe' },
  asset: { key: 'groundwork/ipc-ex1/safety', name: 'Excavator EX1 safety' },
  agent: { id: 'a', name: 'Maintenance tech' },
  reason: 'Oil 76.5°C, rising 3 °C/min',
  current: { value: 'auto' },
};

describe('the command approval card', () => {
  it('charts the signal that fired the rule and shows a text signal as states', () => {
    render(
      <CommandApproval
        pending={false}
        payload={{
          ...base,
          history: null,
          states: [{ t: T0, value: 'auto' }, { t: T0 + 120_000, value: 'hold' }, { t: T0 + 240_000, value: 'auto' }],
          evidence: [{ source: 'firing', title: 'Why it asked: Hydraulics oil temp, last 15 minutes', signal: 'Hydraulics/OilTemp_C', unit: 'C', marks: [{ label: 'limit > 75', value: 75 }], points: oil }],
        }}
      />,
    );
    expect(screen.getByText('Why it asked: Hydraulics oil temp, last 15 minutes')).toBeInTheDocument();
    expect(screen.getByTestId('command-history-chart')).toHaveTextContent('red dashes: limit > 75');
    expect(screen.getByTestId('command-states')).toHaveTextContent('auto');
    expect(screen.getByTestId('command-states')).toHaveTextContent('safe');
    expect(screen.getByTestId('command-approval-reason')).toHaveTextContent('Oil 76.5°C');
    expect(screen.queryByText(/not enough history/i)).toBeNull();
  });

  it('never says there is not enough history for a text signal', () => {
    render(<CommandApproval pending={false} payload={{ ...base, history: { minutes: 15, points: [{ t: T0, avg: null, min: null, max: null }] }, states: null, evidence: [] }} />);
    expect(screen.queryByTestId('command-history-empty')).toBeNull();
    expect(screen.queryByText(/not enough history/i)).toBeNull();
  });

  it('charts a number it is about to change, with the new value marked', () => {
    render(
      <CommandApproval
        pending={false}
        payload={{ ...base, command: { ...base.command, device: '', signal: 'Setpoint_kW', value: 57 }, current: { value: 50 }, history: { minutes: 15, points: oil }, states: null, evidence: [] }}
      />,
    );
    expect(screen.getByTestId('command-history-chart')).toHaveTextContent('amber dashes: the new value');
  });
});

describe('the evidence chart', () => {
  it('names a limit far from the readings instead of flattening them', async () => {
    const { HistoryChart } = await import('@/components/approvals/CommandApproval');
    render(<HistoryChart points={oil} marks={[{ label: 'limit > 1', value: 1 }]} unit="V" />);
    const fig = screen.getByTestId('command-history-chart');
    expect(fig).toHaveTextContent('limit > 1 is below the chart');
    expect(fig).not.toHaveTextContent('red dashes');
  });
});

describe('the state timeline', () => {
  it('says since when for the state it is in, and marks when it was asked apart from it', async () => {
    const { StateTimeline } = await import('@/components/approvals/CommandApproval');
    const changed = Date.UTC(2026, 9, 12, 2, 16);
    const asked = Date.UTC(2026, 9, 12, 3, 34);
    render(<StateTimeline states={[{ t: changed, value: 'auto' }]} next="safe" askedAt={asked} />);
    const fmt = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    expect(screen.getByTestId('command-state-now')).toHaveTextContent(`since ${fmt(changed)}`);
    expect(screen.getByTestId('command-state-now')).not.toHaveTextContent('when asked');
    expect(screen.getByTestId('command-asked-at')).toHaveTextContent(`asked ${fmt(asked)}`);
  });

  it('says since before when the window began in that state', async () => {
    const { StateTimeline } = await import('@/components/approvals/CommandApproval');
    render(<StateTimeline states={[{ t: T0, value: 'auto', before: true }, { t: T0 + 60_000, value: 'hold' }]} next="safe" />);
    expect(screen.getAllByTestId('command-state')[0]).toHaveTextContent('before');
    expect(screen.getByTestId('command-state-now')).toHaveTextContent('since');
  });
});

describe('rule lines on the evidence chart', () => {
  it('draws the normal level and the trigger level of a deviation rule', async () => {
    const { HistoryChart } = await import('@/components/approvals/CommandApproval');
    const temps = [0, 1, 2, 3].map((i) => ({ t: T0 + i * 60_000, avg: 55 + i * 3, min: 54 + i * 3, max: 56 + i * 3 }));
    render(<HistoryChart points={temps} unit="C" marks={[{ label: 'normal 55.7 °C, last 30 min', value: 55.7, kind: 'normal' }, { label: 'fires above 64.1 °C', value: 64.1, kind: 'limit' }]} />);
    const fig = screen.getByTestId('command-history-chart');
    expect(fig).toHaveTextContent('grey dots: normal 55.7 °C, last 30 min');
    expect(fig).toHaveTextContent('red dashes: fires above 64.1 °C');
  });

  it('shades the silence of a stale rule', async () => {
    const { HistoryChart } = await import('@/components/approvals/CommandApproval');
    render(<HistoryChart points={oil} gap={{ from: T0 + 180_000, to: T0 + 240_000, label: 'no data for 60 s' }} />);
    expect(screen.getByTestId('command-history-chart')).toHaveTextContent('shaded: no data for 60 s');
  });

  it('gives a rule with no level a plain caption', () => {
    render(
      <CommandApproval
        pending={false}
        payload={{ ...base, history: null, states: null, evidence: [{ source: 'firing', title: 'Why it asked: HT1 left the haul road', signal: null, points: [], caption: 'Fires when it leaves the haul road. The position is on the Telemetry map.' }] }}
      />,
    );
    expect(screen.getByTestId('command-evidence-caption')).toHaveTextContent('Fires when it leaves the haul road');
    expect(screen.queryByTestId('command-history-chart')).toBeNull();
  });
});
