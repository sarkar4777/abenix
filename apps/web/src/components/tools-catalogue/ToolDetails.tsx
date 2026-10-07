'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { Check, Copy, Wand2 } from 'lucide-react';
import { buildExampleArgs, schemaParams } from './toolSchema';

interface Props {
  id: string;
  description: string;
  inputSchema?: Record<string, unknown>;
}

export default function ToolDetails({ id, description, inputSchema }: Props) {
  const params = useMemo(() => schemaParams(inputSchema), [inputSchema]);
  const example = useMemo(() => JSON.stringify(buildExampleArgs(inputSchema), null, 2), [inputSchema]);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(example);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-3 space-y-4" data-testid={`tool-details-${id}`}>
      {description && <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">{description}</p>}

      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Arguments</h3>
        {!inputSchema ? (
          <p className="text-sm text-amber-300/90">
            This tool publishes no argument schema, so the agent works out the arguments from the description above.
          </p>
        ) : params.length === 0 ? (
          <p className="text-sm text-slate-400">This tool takes no arguments.</p>
        ) : (
          <div className="rounded-lg border border-slate-800 overflow-hidden">
            <div className="hidden sm:grid grid-cols-[minmax(0,1.1fr)_minmax(0,0.8fr)_minmax(0,2.4fr)_minmax(0,0.9fr)] gap-3 px-3 py-2 bg-slate-900 text-[11px] uppercase tracking-wide text-slate-500">
              <span>Name</span><span>Type</span><span>Description</span><span>Default</span>
            </div>
            <ul className="divide-y divide-slate-800">
              {params.map((p) => (
                <li key={p.name} className="grid gap-1 sm:gap-3 sm:grid-cols-[minmax(0,1.1fr)_minmax(0,0.8fr)_minmax(0,2.4fr)_minmax(0,0.9fr)] px-3 py-2 text-sm">
                  <span className="min-w-0 break-words">
                    <code className="font-mono text-cyan-300">{p.name}</code>
                    {p.required
                      ? <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-rose-500/10 text-rose-300 border border-rose-500/30">required</span>
                      : <span className="ml-1.5 text-[10px] text-slate-500">optional</span>}
                  </span>
                  <span className="min-w-0 break-words text-slate-400 font-mono text-xs sm:pt-0.5">{p.type}</span>
                  <span className="min-w-0 break-words text-slate-300">
                    {p.description || <span className="text-slate-500">No description.</span>}
                    {p.enumValues && p.enumValues.length > 0 && (
                      <span className="block text-xs text-slate-500 mt-0.5">
                        One of: {p.enumValues.map((v) => JSON.stringify(v)).join(', ')}
                      </span>
                    )}
                  </span>
                  <span className="min-w-0 break-words text-xs font-mono text-slate-400 sm:pt-0.5">
                    <span className="sm:hidden text-slate-500 font-sans">Default: </span>
                    {p.hasDefault ? JSON.stringify(p.defaultValue) : <span className="text-slate-600">none</span>}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {inputSchema && params.length > 0 && (
        <div>
          <div className="flex items-center justify-between gap-2 mb-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Example arguments</h3>
            <button type="button" onClick={copy} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-white">
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />} {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <pre className="text-xs font-mono text-slate-200 bg-slate-950 border border-slate-800 rounded-lg p-3 overflow-x-auto">{example}</pre>
          <p className="text-[11px] text-slate-500 mt-1">Built from the schema. Values in angle brackets are placeholders to replace.</p>
        </div>
      )}

      <Link
        href={`/builder?tool=${encodeURIComponent(id)}`}
        className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400"
        data-testid={`tool-use-${id}`}
      >
        <Wand2 className="w-4 h-4" /> Use in an agent
      </Link>
    </div>
  );
}
