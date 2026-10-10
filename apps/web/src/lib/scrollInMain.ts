// scroll only the nearest scrolling box, so the top bar and the app frame stay put
export function scrollInMain(el: Element | null | undefined, block: 'start' | 'center' = 'start'): void {
  if (!el || typeof window === 'undefined') return;
  let box: HTMLElement | null = el.parentElement;
  while (box) {
    const oy = getComputedStyle(box).overflowY;
    if ((oy === 'auto' || oy === 'scroll') && box.scrollHeight > box.clientHeight) break;
    box = box.parentElement;
  }
  if (!box) {
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    return;
  }
  const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  const offset = block === 'center' ? Math.max(0, (box.clientHeight - (el as HTMLElement).offsetHeight) / 2) : 16;
  box.scrollTo({ top: Math.max(0, top - offset), behavior: 'smooth' });
}
