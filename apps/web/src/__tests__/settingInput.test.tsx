import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/ModelPicker', () => ({ default: () => <div data-testid="model-picker" /> }));

import SettingInput, { choiceLabel } from '@/components/settings/SettingInput';

describe('SettingInput', () => {
  it('renders a choice as a select with plain labels', () => {
    const onChange = vi.fn();
    render(<SettingInput spec={{ key: 'telemetry.rules_mode', value: 'inprocess', kind: 'choice', choices: ['inprocess', 'pool'] }} value="inprocess" onChange={onChange} />);
    const select = screen.getByLabelText('telemetry.rules_mode') as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => o.text)).toEqual(['Inside the ingest service', 'A separate pool of workers']);
    fireEvent.change(select, { target: { value: 'pool' } });
    expect(onChange).toHaveBeenCalledWith('pool');
    expect(screen.queryByTestId('model-picker')).toBeNull();
  });
  it('takes labels from the server when it gives them, and tidies the rest', () => {
    expect(choiceLabel({ value: 'fast_path', label: 'Fast path' })).toBe('Fast path');
    expect(choiceLabel('fast_path')).toBe('Fast path');
  });
  it('renders a string as a text box, and an unknown kind as text with a note, never a model picker', () => {
    render(<SettingInput spec={{ key: 'a.string', value: 'x', kind: 'string' }} value="x" onChange={() => {}} />);
    expect(screen.getByTestId('text-a.string')).toBeInTheDocument();
    render(<SettingInput spec={{ key: 'a.json', value: '{}', kind: 'json' }} value="{}" onChange={() => {}} />);
    expect(screen.getByTestId('text-a.json')).toHaveTextContent('edited as text');
    expect(screen.queryByTestId('model-picker')).toBeNull();
  });
  it('keeps the model picker for model settings and the number box for int', () => {
    render(<SettingInput spec={{ key: 'm', value: 'claude', kind: 'model' }} value="claude" onChange={() => {}} />);
    expect(screen.getByTestId('model-picker')).toBeInTheDocument();
    render(<SettingInput spec={{ key: 'n', value: '5', kind: 'int', min: 1, max: 10 }} value="5" onChange={() => {}} />);
    expect(screen.getByTestId('number-n')).toHaveTextContent('allowed 1 to 10');
  });
});
