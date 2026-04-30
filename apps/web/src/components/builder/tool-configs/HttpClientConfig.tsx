'use client';

/**
 * HttpClientConfig — schema-driven form for `http_client` PLUS a
 * "Import from cURL" affordance. The import path is the only reason
 * this component exists; everything else is delegated to
 * ToolConfigFields so we don't fork the field rendering.
 */
import { useState } from 'react';
import { Wand2, Loader2, X, AlertTriangle, CheckCircle2 } from 'lucide-react';
import ToolConfigFields from './ToolConfigFields';
import { getToolDoc } from '@/lib/tool-docs';
import { parseCurl } from '@/lib/curl-parser';

interface Props {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function HttpClientConfig({ values, onChange }: Props) {
  const doc = getToolDoc('http_client');
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const [feedback, setFeedback] = useState<{ ok: boolean; message: string } | null>(null);
  const [importing, setImporting] = useState(false);

  const applyImport = () => {
    setImporting(true);
    try {
      const parsed = parseCurl(text);
      if (!parsed.url) {
        setFeedback({ ok: false, message: 'No URL detected — paste a full cURL command.' });
        setImporting(false);
        return;
      }
      const next: Record<string, unknown> = { ...values, url: parsed.url, method: parsed.method };
      if (Object.keys(parsed.headers).length > 0) next.headers = parsed.headers;
      if (Object.keys(parsed.params).length > 0) next.params = parsed.params;
      if (parsed.body != null) next.body = parsed.body;
      if (parsed.bearer_token) next.bearer_token = parsed.bearer_token;
      onChange(next);
      const note = parsed.warnings.length > 0
        ? ` (${parsed.warnings.length} warning${parsed.warnings.length === 1 ? '' : 's'})`
        : '';
      setFeedback({ ok: true, message: `Imported ${parsed.method} ${parsed.url}${note}` });
      setTimeout(() => { setOpen(false); setText(''); setFeedback(null); }, 900);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to parse';
      setFeedback({ ok: false, message: msg });
    }
    setImporting(false);
  };

  return (
    <div className="space-y-3" data-testid="http-client-config">
      {/* Import button */}
      <button
        type="button"
        data-testid="curl-import-button"
        onClick={() => { setOpen(true); setFeedback(null); }}
        className="w-full text-xs flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-cyan-500/30 bg-cyan-500/5 hover:bg-cyan-500/10 text-cyan-300 transition-colors"
      >
        <Wand2 className="w-3.5 h-3.5" />
        Import from cURL
      </button>

      {/* Modal */}
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
          data-testid="curl-import-modal"
          onClick={(e) => { if (e.target === e.currentTarget) { setOpen(false); setFeedback(null); } }}
        >
          <div className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-2xl">
            <div className="flex items-center justify-between p-4 border-b border-slate-700/60">
              <h3 className="text-sm font-medium text-white flex items-center gap-2">
                <Wand2 className="w-4 h-4 text-cyan-300" />
                Paste cURL command
              </h3>
              <button
                onClick={() => { setOpen(false); setFeedback(null); }}
                data-testid="curl-import-close"
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 space-y-3">
              <textarea
                data-testid="curl-import-textarea"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={`curl -X POST https://api.example.com/v1/foo \\\n  -H 'Authorization: Bearer xyz' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"hello": "world"}'`}
                className="w-full font-mono text-xs bg-slate-950 border border-slate-700 rounded-lg p-3 min-h-[180px] text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
              />
              {feedback && (
                <div
                  data-testid={`curl-import-feedback-${feedback.ok ? 'ok' : 'err'}`}
                  className={`text-xs flex items-start gap-2 rounded-lg p-2.5 ${
                    feedback.ok
                      ? 'bg-emerald-500/10 text-emerald-300 ring-1 ring-emerald-500/30'
                      : 'bg-rose-500/10 text-rose-300 ring-1 ring-rose-500/30'
                  }`}
                >
                  {feedback.ok ? <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    : <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
                  <span>{feedback.message}</span>
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <button
                  onClick={() => { setOpen(false); setFeedback(null); }}
                  className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </button>
                <button
                  data-testid="curl-import-apply"
                  onClick={applyImport}
                  disabled={importing || !text.trim()}
                  className="text-xs px-3 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-medium inline-flex items-center gap-1.5 disabled:opacity-50"
                >
                  {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
                  Import
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Schema-driven form (same as default) */}
      {doc && (
        <ToolConfigFields params={doc.parameters} values={values} onChange={onChange} />
      )}
    </div>
  );
}
