import { render, renderHook, screen, fireEvent } from '@testing-library/react';
import { deepLinkParam, matchModel, resolveDeepLink, useDeepLink } from '@/lib/deep-link';
import DeepLinkMissing from '@/components/shared/DeepLinkMissing';

const items = [{ id: 'a1', name: 'one' }, { id: 'b2', name: 'two' }];

describe('deepLinkParam', () => {
  it('takes the first key that has a value', () => {
    expect(deepLinkParam(new URLSearchParams('id=x&asset=y'), ['asset', 'id'])).toBe('y');
    expect(deepLinkParam(new URLSearchParams('id=x'), ['asset', 'id'])).toBe('x');
    expect(deepLinkParam(new URLSearchParams('asset=%20'), ['asset'])).toBeNull();
    expect(deepLinkParam(null, ['asset'])).toBeNull();
  });
});

describe('resolveDeepLink', () => {
  it('waits for data, then finds or misses', () => {
    expect(resolveDeepLink(items, null).state).toBe('none');
    expect(resolveDeepLink(undefined, 'a1').state).toBe('waiting');
    expect(resolveDeepLink(items, 'b2')).toEqual({ state: 'found', item: items[1] });
    expect(resolveDeepLink(items, 'zz')).toEqual({ state: 'missing', item: null });
  });
});

describe('matchModel', () => {
  const models = [
    { id: 'm1', name: 'churn', is_active: false },
    { id: 'm2', name: 'churn', is_active: true },
    { id: 'm3', name: 'risk' },
  ];
  const pick = (w: string) => models.find((m) => matchModel(m, w, models))?.id;
  it('matches an id, or a name by its active version', () => {
    expect(pick('m1')).toBe('m1');
    expect(pick('churn')).toBe('m2');
    expect(pick('risk')).toBe('m3');
    expect(pick('nope')).toBeUndefined();
  });
});

describe('useDeepLink', () => {
  it('opens the item once the list loads and only once', () => {
    const open = vi.fn();
    const { result, rerender } = renderHook(({ list, id }) => useDeepLink(list, id, open), {
      initialProps: { list: undefined as typeof items | undefined, id: 'b2' as string | null },
    });
    expect(open).not.toHaveBeenCalled();
    rerender({ list: items, id: 'b2' });
    expect(open).toHaveBeenCalledWith(items[1]);
    rerender({ list: [...items], id: 'b2' });
    expect(open).toHaveBeenCalledTimes(1);
    expect(result.current).toBeNull();
  });

  it('reports an id that is not in the list, and clears when the link goes', () => {
    const open = vi.fn();
    const { result, rerender } = renderHook(({ id }) => useDeepLink(items, id, open), {
      initialProps: { id: 'gone' as string | null },
    });
    expect(result.current).toBe('gone');
    expect(open).not.toHaveBeenCalled();
    rerender({ id: null });
    expect(result.current).toBeNull();
  });
});

describe('DeepLinkMissing', () => {
  it('names the item and can be dismissed', () => {
    const onDismiss = vi.fn();
    render(<DeepLinkMissing noun="model" id="m9" onDismiss={onDismiss} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Could not open the model m9');
    fireEvent.click(screen.getByLabelText('Dismiss'));
    expect(onDismiss).toHaveBeenCalled();
  });
});
