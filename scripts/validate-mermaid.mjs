// Validate every Mermaid block under docs/ by parsing with the real
// mermaid library — same one the docs viewer uses. Exits non-zero if
// any block fails to parse.
//
// Usage:
//   node scripts/validate-mermaid.mjs

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const DOCS = path.join(ROOT, 'docs');

// Mermaid expects a DOM at import time (DOMPurify init). Provide one.
const { JSDOM } = await import(pathToFileURL(path.join(ROOT, 'node_modules', 'jsdom', 'lib', 'api.js')).href);
const dom = new JSDOM('<!DOCTYPE html><body></body>');
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.DocumentFragment = dom.window.DocumentFragment;
globalThis.Node = dom.window.Node;

let mermaid;
try {
  const mermaidPath = path.join(ROOT, 'node_modules', 'mermaid', 'dist', 'mermaid.core.mjs');
  const mod = await import(pathToFileURL(mermaidPath).href);
  mermaid = mod.default;
} catch (e) {
  console.error('Could not load mermaid:', e.message);
  process.exit(2);
}

// Don't initialize — that calls DOMPurify which needs a DOM.
// mermaid.parse() does syntax-only parsing and doesn't need the DOM.

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.')) continue;
    if (entry.name === 'assets' || entry.name === 'screenshots') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.name.endsWith('.md')) out.push(full);
  }
  return out;
}

function extract(md) {
  const blocks = [];
  const lines = md.split('\n');
  let i = 0;
  while (i < lines.length) {
    if (lines[i].trim() === '```mermaid') {
      const start = i + 1;
      let j = i + 1;
      while (j < lines.length && lines[j].trim() !== '```') j++;
      blocks.push({ start: start + 1, end: j, content: lines.slice(start, j).join('\n') });
      i = j + 1;
    } else {
      i++;
    }
  }
  return blocks;
}

const failures = [];
const files = walk(DOCS);
let totalBlocks = 0;

for (const file of files) {
  const rel = path.relative(ROOT, file);
  const blocks = extract(fs.readFileSync(file, 'utf8'));
  for (const block of blocks) {
    totalBlocks++;
    try {
      await mermaid.parse(block.content);
    } catch (e) {
      failures.push({
        file: rel,
        line: block.start,
        error: String(e?.message || e).split('\n').slice(0, 4).join('\n'),
        preview: block.content.split('\n').slice(0, 6).join('\n'),
      });
    }
  }
}

console.log(`Validated ${totalBlocks} mermaid blocks across ${files.length} markdown files.`);
if (failures.length === 0) {
  console.log('All blocks parsed cleanly.');
  process.exit(0);
}

console.log(`\n${failures.length} broken block(s):\n`);
for (const f of failures) {
  console.log(`✗ ${f.file}:${f.line}`);
  console.log(`  ${f.error.split('\n').join('\n  ')}`);
  console.log(`  --- preview ---`);
  console.log(`  ${f.preview.split('\n').join('\n  ')}`);
  console.log();
}
process.exit(1);
