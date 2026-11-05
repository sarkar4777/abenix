import fs from 'node:fs';
import path from 'node:path';
import { HERO_STATS } from '@/components/landing/HeroSection';

const ROOT = path.resolve(__dirname, '../../../..');
const claim = (label: string) => HERO_STATS.find((s) => s.label === label)!.value;

describe('landing page numbers', () => {
  it('claim no more agents than the repo seeds', () => {
    const seeds = fs.readdirSync(path.join(ROOT, 'packages/db/seeds/agents')).filter((f) => /\.ya?ml$/.test(f));
    expect(seeds.length).toBeGreaterThanOrEqual(claim('Pre-Built Agents'));
  });

  it('claim no more test suites than the repo has', () => {
    const specs = fs.readdirSync(path.join(ROOT, 'e2e')).filter((f) => f.endsWith('.spec.ts'));
    expect(specs.length).toBeGreaterThanOrEqual(claim('Test Suites'));
  });
});
