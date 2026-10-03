import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ChatMessage from '@/components/chat/ChatMessage';

describe('chat markdown', () => {
  it('renders an agent table as a table, with headings and lists', () => {
    const content = [
      '### Base case',
      '',
      '| Time | Action |',
      '|---|---|',
      '| 20:45 | Discharge 50 MW |',
      '',
      '- first risk',
    ].join('\n');
    render(<ChatMessage role="assistant" blocks={[{ type: 'text', content }]} />);
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByRole('cell', { name: 'Discharge 50 MW' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Base case' })).toBeTruthy();
    expect(screen.getByRole('listitem').textContent).toBe('first risk');
  });
});
