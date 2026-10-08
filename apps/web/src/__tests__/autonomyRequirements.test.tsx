import { render, screen, within } from '@testing-library/react';

vi.mock('next/link', () => ({
  default: ({ href, children, prefetch: _p, ...rest }: any) => <a href={href} {...rest}>{children}</a>,
}));

import RequirementList from '@/components/autonomy/RequirementList';
import LevelPill from '@/components/autonomy/LevelPill';
import Ladder from '@/components/autonomy/Ladder';
import Sparkline from '@/components/autonomy/Sparkline';
import TrackRecordChart from '@/components/autonomy/TrackRecordChart';

describe('RequirementList', () => {
  it('renders each requirement with progress and a fix link when unmet', () => {
    render(
      <RequirementList
        requirements={[
          { key: 'min_executed', label: '34 of 50 scored actions', current: 34, needed: 50, met: false, fix: { label: 'Run the sample agent', href: '/autonomy/g1' } },
          { key: 'min_accuracy_lb', label: 'Accuracy 91% (needs 85%)', current: 0.91, needed: 0.85, met: true, fix: { label: 'never shown', href: '/x' } },
        ]}
      />,
    );
    const unmet = screen.getByTestId('autonomy-requirement-min_executed');
    expect(unmet).toHaveAttribute('data-met', 'false');
    expect(within(unmet).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '68');
    expect(within(unmet).getByRole('link', { name: /Run the sample agent/ })).toHaveAttribute('href', '/autonomy/g1');

    const met = screen.getByTestId('autonomy-requirement-min_accuracy_lb');
    expect(met).toHaveAttribute('data-met', 'true');
    expect(within(met).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
    expect(within(met).queryByRole('link')).toBeNull();
  });

  it('says so when there are no checks', () => {
    render(<RequirementList requirements={[]} />);
    expect(screen.getByTestId('autonomy-requirements-empty')).toBeInTheDocument();
  });
});

describe('LevelPill and Ladder', () => {
  it('shows the label, never the bare number', () => {
    render(<LevelPill level={2} />);
    const pill = screen.getByTestId('autonomy-level-pill');
    expect(pill).toHaveTextContent('Asks first');
    expect(pill).toHaveAttribute('data-level', '2');
  });

  it('marks the current step on the ladder', () => {
    render(<Ladder level={1} ceiling={2} />);
    expect(screen.getByTestId('autonomy-ladder-step-watching')).toHaveAttribute('data-current', 'true');
    expect(screen.getByTestId('autonomy-ladder-step-asks_first')).toHaveAttribute('data-current', 'false');
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });
});

describe('charts', () => {
  it('sparkline says when there is nothing yet', () => {
    render(<Sparkline values={[]} />);
    expect(screen.getByTestId('autonomy-spark-empty')).toHaveTextContent('No results yet');
  });

  it('sparkline counts held results', () => {
    render(<Sparkline values={[1, 0, 1, null]} />);
    expect(screen.getByTestId('autonomy-spark')).toHaveAttribute('aria-label', '2 of the last 3 results held');
  });

  it('track record draws a dot per actual and the markers', () => {
    render(
      <TrackRecordChart
        points={[
          { id: 'a', value: 4.4, low: 4.1, high: 4.6, actual: 4.3, within_band: true },
          { id: 'b', value: 4.4, low: 4.1, high: 4.6, actual: 5.0, within_band: false, revision_marker: true },
          { id: 'c', value: 4.5, low: 4.2, high: 4.8, actual: null, within_band: null },
        ]}
      />,
    );
    expect(screen.getAllByTestId('autonomy-chart-dot')).toHaveLength(2);
    expect(screen.getByTestId('autonomy-chart-revision')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('aria-label', 'Track record: 1 inside the band, 1 outside, of 3 actions');
  });

  it('track record has an empty state', () => {
    render(<TrackRecordChart points={[]} />);
    expect(screen.getByTestId('autonomy-chart-empty')).toBeInTheDocument();
  });
});
