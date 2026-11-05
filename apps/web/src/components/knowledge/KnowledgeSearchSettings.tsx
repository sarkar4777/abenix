'use client';

import { useState } from 'react';
import { Languages, Loader2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { INDEX_MODE_HELP, LANGUAGE_HELP, SEARCH_LANGUAGES, languageLabel } from '@/lib/knowledge-settings';

export function KnowledgeSearchSettings({
  kbId,
  language,
  indexMode,
  canEdit,
  onChanged,
}: {
  kbId: string;
  language: string;
  indexMode: string;
  canEdit: boolean;
  onChanged: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const base = `/api/knowledge-bases/${kbId}`;

  const send = async (path: string, method: string, body?: object) => {
    setBusy(true);
    setProblem('');
    const res = await apiFetch(path, {
      method,
      body: body ? JSON.stringify(body) : undefined,
      throwOnError: false,
      silent: true,
    });
    setBusy(false);
    if (res.error) setProblem(res.error);
    else await onChanged();
  };

  return (
    <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3" data-testid="kb-search-settings">
      <h3 className="text-sm font-semibold text-white flex items-center gap-2">
        <Languages className="w-4 h-4 text-cyan-400" />
        Search settings
      </h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label htmlFor="kb-language" className="block text-xs text-slate-400 mb-1.5">Language</label>
          <select
            id="kb-language"
            data-testid="kb-language"
            value={language}
            disabled={!canEdit || busy}
            onChange={(e) => send(base, 'PUT', { search_language: e.target.value })}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500 disabled:opacity-60"
          >
            {SEARCH_LANGUAGES.map((l) => <option key={l} value={l}>{languageLabel(l)}</option>)}
          </select>
          <p className="text-[11px] text-slate-500 mt-1">{LANGUAGE_HELP}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400 mb-1.5">Vector index</p>
          <p className="text-sm text-white capitalize" data-testid="kb-index-mode">{indexMode}</p>
          <p className="text-[11px] text-slate-500 mt-1">{INDEX_MODE_HELP[indexMode] ?? ''}</p>
          {canEdit && indexMode === 'shared' && (
            <button onClick={() => send(base, 'PUT', { index_mode: 'deferred' })} disabled={busy} data-testid="kb-index-defer" className="mt-2 text-xs text-cyan-400 hover:underline disabled:opacity-50">
              Wait with the index for a bulk load
            </button>
          )}
          {canEdit && indexMode === 'deferred' && (
            <button onClick={() => send(`${base}/index/build`, 'POST')} disabled={busy} data-testid="kb-index-build" className="mt-2 text-xs text-cyan-400 hover:underline disabled:opacity-50">
              Build the index now
            </button>
          )}
        </div>
      </div>
      {busy && <p className="text-xs text-slate-500 flex items-center gap-2"><Loader2 className="w-3 h-3 animate-spin" /> Saving…</p>}
      {problem && <p role="alert" data-testid="kb-search-settings-error" className="text-xs text-rose-300">{problem}</p>}
    </div>
  );
}
