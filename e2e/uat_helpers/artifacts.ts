import * as fs from 'node:fs';
import * as path from 'node:path';

// matches the e2e/test-results*/ ignore rule, and Playwright does not wipe it between runs
const ROOT = path.resolve(__dirname, '..', 'test-results-artifacts');

export function artifactDir(name: string): string {
  const dir = path.join(ROOT, name);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}
