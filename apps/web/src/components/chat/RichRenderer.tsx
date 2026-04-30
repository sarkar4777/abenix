'use client';


import { useEffect, useRef, useState } from 'react';

// 1. FEN / chess board

// A FEN string: 8 rows of [pnbrqkPNBRQK1-8]+, separated by /, then a space
// and the side-to-move, castling, etc. We just match the board part.
const FEN_RE = /(?:^|\s|"fen"\s*:\s*")([prnbqkPRNBQK1-8]{1,8}(?:\/[prnbqkPRNBQK1-8]{1,8}){7})(?:\s+[wb]\s+[KQkq-]+|")/;

const PIECE_TO_UNICODE: Record<string, string> = {
  K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
  k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
};

function fenToBoard(fen: string): string[][] {
  const rows = fen.split('/');
  return rows.map((row) => {
    const cells: string[] = [];
    for (const ch of row) {
      if (/\d/.test(ch)) {
        for (let i = 0; i < parseInt(ch, 10); i++) cells.push('');
      } else {
        cells.push(ch);
      }
    }
    return cells;
  });
}

function ChessBoard({ fen, orientation = 'white' }: { fen: string; orientation?: 'white' | 'black' }) {
  const board = fenToBoard(fen);
  const rows = orientation === 'black' ? [...board].reverse() : board;
  return (
    <div className="my-3">
      <div className="inline-grid grid-cols-8 border-2 border-slate-600 rounded overflow-hidden shadow-lg">
        {rows.map((row, r) =>
          (orientation === 'black' ? [...row].reverse() : row).map((piece, c) => {
            const light = (r + c) % 2 === 0;
            return (
              <div
                key={`${r}-${c}`}
                className={`w-10 h-10 flex items-center justify-center text-2xl leading-none ${
                  light ? 'bg-amber-100' : 'bg-emerald-800'
                }`}
              >
                <span className={piece && piece === piece.toUpperCase() ? 'text-slate-900' : 'text-slate-900'}>
                  {PIECE_TO_UNICODE[piece] || ''}
                </span>
              </div>
            );
          })
        )}
      </div>
      <p className="text-[10px] font-mono text-slate-500 mt-1">{fen}</p>
    </div>
  );
}

// 2. Mermaid

function MermaidBlock({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [svg, setSvg] = useState<string>('');
  const [err, setErr] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose' });
        const id = `mmd-${Math.random().toString(36).slice(2, 10)}`;
        const out = await mermaid.render(id, code);
        if (!cancelled) setSvg(out.svg);
      } catch (e: any) {
        if (!cancelled) setErr(e?.message || 'mermaid render failed');
      }
    })();
    return () => { cancelled = true; };
  }, [code]);

  if (err) return <pre className="text-xs text-amber-300">{err}\n{code}</pre>;
  return (
    <div
      ref={ref}
      className="bg-slate-950/60 border border-slate-700/50 rounded-lg p-3 my-2 overflow-x-auto"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

// 3. Table

function TableBlock({ headers, rows }: { headers: string[]; rows: (string | number)[][] }) {
  return (
    <div className="my-3 overflow-x-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="text-left px-3 py-1.5 bg-slate-800/60 border border-slate-700 font-medium text-slate-200">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className={r % 2 === 0 ? 'bg-slate-900/40' : 'bg-slate-900/20'}>
              {row.map((cell, c) => (
                <td key={c} className="px-3 py-1 border border-slate-700/50 text-slate-300">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// 4. KV card (used when the agent output is a flat object with a few keys)

function KVBlock({ obj }: { obj: Record<string, unknown> }) {
  return (
    <div className="my-3 rounded-lg border border-slate-700/50 bg-slate-900/40 divide-y divide-slate-800">
      {Object.entries(obj).map(([k, v]) => (
        <div key={k} className="flex items-start gap-3 px-3 py-1.5 text-xs">
          <span className="text-slate-500 font-mono w-32 shrink-0">{k}</span>
          <span className="text-slate-200 break-words">
            {typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

// 5. Image (from a bare URL or image_url key)

function ImageBlock({ src, alt }: { src: string; alt?: string }) {
  return (
    <div className="my-3">
      <img src={src} alt={alt || ''} className="max-w-full rounded-lg border border-slate-700/50" loading="lazy" />
    </div>
  );
}

// Extract the first JSON object embedded in text, if any

function extractJson(text: string): unknown | null {
  const trimmed = text.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try { return JSON.parse(trimmed); } catch { /* ignore */ }
  }
  // Find the first balanced { … } block in the text
  const open = text.indexOf('{');
  if (open === -1) return null;
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    if (text[i] === '{') depth++;
    else if (text[i] === '}') {
      depth--;
      if (depth === 0) {
        try { return JSON.parse(text.slice(open, i + 1)); } catch { return null; }
      }
    }
  }
  return null;
}

// Public API — returns { widgets, remainingText } or null if nothing rich

export interface RichRenderResult {
  widgets: React.ReactNode[];
  remainingText: string;
}

export function renderRich(text: string): RichRenderResult | null {
  if (!text) return null;
  const widgets: React.ReactNode[] = [];
  let remaining = text;

  // 1. Mermaid fenced block(s) — extract + inject widget
  const mermaidRe = /```mermaid\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  let matched = false;
  while ((match = mermaidRe.exec(text)) !== null) {
    widgets.push(<MermaidBlock key={`mmd-${match.index}`} code={match[1].trim()} />);
    matched = true;
  }
  if (matched) {
    remaining = remaining.replace(/```mermaid\n[\s\S]*?```/g, '').trim();
  }

  // 2. FEN chess string anywhere in the text
  const fenMatch = text.match(FEN_RE);
  if (fenMatch) {
    widgets.push(<ChessBoard key={`fen-${fenMatch.index}`} fen={fenMatch[1]} />);
  }

  // 3. Structured JSON at top-level
  const json = extractJson(text);
  if (json && typeof json === 'object' && json !== null) {
    const obj = json as Record<string, unknown>;
    // 3a. explicit board / fen key
    if (typeof obj.fen === 'string') {
      widgets.push(<ChessBoard key="fen-key" fen={obj.fen} />);
    }
    // 3b. explicit image_url
    if (typeof obj.image_url === 'string') {
      widgets.push(<ImageBlock key="img" src={obj.image_url} alt={String(obj.alt || '')} />);
    }
    // 3c. structured table
    if (obj.table && typeof obj.table === 'object') {
      const t = obj.table as { headers?: string[]; rows?: (string | number)[][] };
      if (Array.isArray(t.headers) && Array.isArray(t.rows)) {
        widgets.push(<TableBlock key="tbl" headers={t.headers} rows={t.rows} />);
      }
    }
    // 3d. flat scalar object — render as KV card if ≤ 10 keys, else skip
    const keys = Object.keys(obj);
    const allScalar = keys.every((k) => {
      const v = obj[k];
      return v === null || ['string', 'number', 'boolean'].includes(typeof v);
    });
    if (allScalar && keys.length > 0 && keys.length <= 10 && widgets.length === 0) {
      widgets.push(<KVBlock key="kv" obj={obj} />);
    }
  }

  if (widgets.length === 0) return null;
  return { widgets, remainingText: remaining };
}
