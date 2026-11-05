import { fireEvent, render, screen } from '@testing-library/react';
import ConfigWarnings from '@/components/builder/ConfigWarnings';

describe('builder config warnings', () => {
  it('lists what the API warned about and can be dismissed', () => {
    const onDismiss = vi.fn();
    render(<ConfigWarnings warnings={['Model fake is not in this deployment\'s model list.', 'These tools do not exist and a run will not have them. nope']} onDismiss={onDismiss} />);
    const box = screen.getByTestId('builder-config-warnings');
    expect(box).toHaveTextContent('Saved, but check this before you run it');
    expect(box).toHaveTextContent('Model fake is not');
    expect(box).toHaveTextContent('run will not have them. nope');
    fireEvent.click(screen.getByLabelText('Dismiss warnings'));
    expect(onDismiss).toHaveBeenCalled();
  });
});
