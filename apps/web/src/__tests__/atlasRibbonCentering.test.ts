import { readFileSync } from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

// framer-motion writes its own transform, so a Tailwind translate on an animated element is dropped
describe('atlas proposed-ops ribbon', () => {
  const src = readFileSync(path.join(__dirname, '../app/(app)/atlas/page.tsx'), 'utf8');
  const motionTags = src.match(/<motion\.div[\s\S]*?>/g) || [];

  it('does not centre an animated element with a translate class', () => {
    const bad = motionTags.filter((t) => /animate=\{\{[^}]*\b[xy]:/.test(t) && /-translate-[xy]-/.test(t));
    expect(bad).toEqual([]);
  });

  it('keeps the ribbon centred inside the canvas', () => {
    const ribbon = motionTags.find((t) => t.includes('w-[640px]'));
    expect(ribbon).toContain('inset-x-0 mx-auto');
  });
});
