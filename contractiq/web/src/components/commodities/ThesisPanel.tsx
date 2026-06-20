'use client';

import React from 'react';

export interface Driver {
  category?: string;
  headline?: string;
  source?: string;
  url?: string;
  date?: string;
  impact?: string | number;
}

interface Props {
  summary?: string | null;
  narrativeMarkdown?: string | null;
  drivers?: Driver[] | null;
  confidence?: number | null;
}

function fmtConfidence(c?: number | null): string {
  if (c == null || isNaN(c)) return '';
  const v = c > 1 ? c : c * 100;
  return `${v.toFixed(0)}% confidence`;
}

// Tiny markdown renderer. We don't ship react-markdown in this app, so
// inline a small parser that handles the cases the thesis agent actually
// emits: bold (**x**), italics (*x*), inline code (`x`), headings (#..),
// unordered lists (- x), blank-line paragraphs. No HTML pass-through;
// raw tags are escaped.
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function inlineMd(s: string): string {
  let out = escapeHtml(s);
  // Bold first (greedy enough to bind tightly thanks to the inner [^*])
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  // Italics — leave standalone asterisks alone.
  out = out.replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,!?:;]|$)/g, '$1<em>$2</em>');
  // Inline code
  out = out.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 rounded bg-slate-800 text-amber-200 text-[10px]">$1</code>');
  // Linkify bare http(s):// urls
  out = out.replace(
    /(https?:\/\/[^\s)<>"']+)/g,
    '<a href="$1" target="_blank" rel="noreferrer" class="text-emerald-300 underline">$1</a>',
  );
  return out;
}

function renderMarkdown(md: string): React.ReactNode {
  const lines = md.replace(/\r\n?/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    // Skip blank
    if (!line.trim()) {
      i += 1;
      continue;
    }
    // Headings
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2];
      const sizes = ['text-base', 'text-sm', 'text-sm', 'text-xs', 'text-xs', 'text-xs'];
      blocks.push(
        React.createElement(`h${Math.min(level + 2, 6)}`, {
          key: key++,
          className: `font-semibold text-white ${sizes[level - 1]} mt-3 mb-1`,
          dangerouslySetInnerHTML: { __html: inlineMd(text) },
        }),
      );
      i += 1;
      continue;
    }
    // Unordered list
    if (/^[\-\*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[\-\*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[\-\*]\s+/, ''));
        i += 1;
      }
      blocks.push(
        <ul key={key++} className="list-disc pl-5 my-2 space-y-1 text-slate-300">
          {items.map((it, idx) => (
            <li
              key={idx}
              className="text-xs leading-relaxed"
              dangerouslySetInnerHTML={{ __html: inlineMd(it) }}
            />
          ))}
        </ul>,
      );
      continue;
    }
    // Paragraph — collect contiguous non-blank lines
    const para: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^[\-\*]\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p
        key={key++}
        className="text-xs text-slate-300 leading-relaxed my-2"
        dangerouslySetInnerHTML={{ __html: inlineMd(para.join(' ')) }}
      />,
    );
  }
  return blocks;
}

export function ThesisPanel({ summary, narrativeMarkdown, drivers, confidence }: Props) {
  const hasContent = !!(summary || narrativeMarkdown || (drivers && drivers.length));

  if (!hasContent) {
    return (
      <div
        data-testid="thesis-empty"
        className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 text-xs text-slate-500"
      >
        Run analysis to generate a thesis narrative.
      </div>
    );
  }

  return (
    <div data-testid="thesis-panel" className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-sm font-semibold text-white">Thesis</h2>
        {confidence != null && (
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            {fmtConfidence(confidence)}
          </span>
        )}
      </div>
      {summary && <p className="text-sm text-slate-200 leading-relaxed mb-3">{summary}</p>}
      {narrativeMarkdown && (
        <div data-testid="thesis-narrative" className="mb-3">
          {renderMarkdown(narrativeMarkdown)}
        </div>
      )}
      {drivers && drivers.length > 0 && (
        <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
          {drivers.map((d, i) => (
            <a
              key={i}
              href={d.url || '#'}
              target={d.url ? '_blank' : undefined}
              rel="noreferrer"
              className="block rounded-md border border-slate-800 bg-slate-900/60 p-3 hover:border-slate-700 transition-colors"
            >
              <div className="flex items-baseline justify-between gap-2">
                {d.category && (
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">
                    {d.category}
                  </span>
                )}
                {d.impact != null && (
                  <span className="text-[10px] font-mono text-emerald-300">
                    {String(d.impact)}
                  </span>
                )}
              </div>
              {d.headline && <p className="text-xs text-slate-200 mt-1">{d.headline}</p>}
              <p className="text-[10px] text-slate-500 mt-1">
                {[d.source, d.date].filter(Boolean).join(' · ')}
              </p>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export default ThesisPanel;
