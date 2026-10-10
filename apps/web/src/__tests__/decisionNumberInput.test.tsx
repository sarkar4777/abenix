import { describe, expect, it } from 'vitest';
import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NumberInput } from '@/components/decisions/DraftInput';
import ValueInput from '@/components/decisions/ValueInput';
import type { Condition } from '@/lib/decisions';

function Harness({ start }: { start?: any }) {
  const [v, setV] = useState<any>(start);
  return (
    <>
      <NumberInput aria-label="n" value={v} onValue={setV} />
      <output data-testid="out">{JSON.stringify(v ?? null)}</output>
    </>
  );
}

function CondHarness() {
  const [c, setC] = useState<Condition>({ fact: 'speed', op: 'gte' });
  return (
    <>
      <ValueInput cond={c} type="number" onChange={(p) => setC((x) => ({ ...x, ...p }))} referenceSets={[]} testId="v" />
      <output data-testid="cond">{JSON.stringify(c.value ?? null)}</output>
    </>
  );
}

describe('a number typed key by key', () => {
  it.each([['0.5', 0.5], ['2.50', 2.5], ['4.5', 4.5], ['-1.25', -1.25]])('%s keeps its point', async (typed, want) => {
    render(<Harness />);
    const input = screen.getByLabelText('n') as HTMLInputElement;
    await userEvent.type(input, typed);
    expect(input.value).toBe(typed);
    expect(JSON.parse(screen.getByTestId('out').textContent!)).toBe(want);
  });

  it('passes on words so they can be flagged', async () => {
    render(<Harness />);
    await userEvent.type(screen.getByLabelText('n'), 'fifty');
    expect(screen.getByTestId('out').textContent).toBe('"fifty"');
  });

  it('shows a change made somewhere else', async () => {
    const { rerender } = render(<NumberInput aria-label="n" value={3} onValue={() => {}} />);
    rerender(<NumberInput aria-label="n" value={7} onValue={() => {}} />);
    expect((screen.getByLabelText('n') as HTMLInputElement).value).toBe('7');
  });

  it('works inside a rule condition', async () => {
    render(<CondHarness />);
    const input = screen.getByTestId('v') as HTMLInputElement;
    await userEvent.type(input, '0.5');
    expect(input.value).toBe('0.5');
    expect(screen.getByTestId('cond').textContent).toBe('0.5');
    expect(input.placeholder).not.toBe('0');
  });
});
