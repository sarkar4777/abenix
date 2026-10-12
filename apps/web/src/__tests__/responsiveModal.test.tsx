import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ResponsiveModal from '@/components/ui/ResponsiveModal';

let wide = true;
const listeners = new Set<(e: { matches: boolean }) => void>();

beforeEach(() => {
  wide = true;
  listeners.clear();
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({
      get matches() { return query.includes('min-width: 768px') ? wide : false; },
      media: query,
      addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => listeners.add(fn),
      removeEventListener: (_: string, fn: (e: { matches: boolean }) => void) => listeners.delete(fn),
      addListener: () => {},
      removeListener: () => {},
    }),
  });
});
afterEach(() => listeners.clear());

function resize(toWide: boolean) {
  wide = toWide;
  act(() => listeners.forEach((fn) => fn({ matches: toWide })));
}

describe('ResponsiveModal', () => {
  it('opens as a dialog on a wide screen from the first frame', () => {
    render(<ResponsiveModal open onClose={() => {}} title="Add a source"><input aria-label="Name" /></ResponsiveModal>);
    // the dialog has a close button in its header and a clickable backdrop, the sheet a full-height panel
    expect(document.querySelector('.h-full.w-full')).toBeNull();
  });

  it('keeps what was typed when the window crosses 768 px while open', () => {
    render(<ResponsiveModal open onClose={() => {}} title="Add a source"><input aria-label="Name" /></ResponsiveModal>);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Site broker' } });
    resize(false);
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Site broker');
    resize(true);
    expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Site broker');
  });

  it('opens as a sheet on a phone', () => {
    wide = false;
    render(<ResponsiveModal open onClose={() => {}} title="Add a source"><input aria-label="Name" /></ResponsiveModal>);
    expect(document.querySelector('.h-full.w-full')).not.toBeNull();
  });
});
