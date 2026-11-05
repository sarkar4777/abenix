'use client';

import { useEffect, useRef, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { apiFetch } from '@/lib/api-client';
import { cognifyBody, cognifyProblem, type CognifyChoices } from '@/lib/knowledge-settings';

interface Estimate {
  documents: number;
  chunks: number;
  chunks_total: number;
  model: string;
  estimated_usd: number;
  max_cost_usd: number;
  note?: string;
}

const FIELD = 'w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500';

const SELECTION_HELP: Record<CognifyChoices['selection'], string> = {
  all: 'Reads every chunk.',
  sample: 'Reads an even sample of the chunks. A rerun picks the same ones.',
  salient: 'Reads the chunks with the most names and numbers first.',
};

export function CognifyStartDialog({
  kbId,
  open,
  onClose,
  onStarted,
}: {
  kbId: string;
  open: boolean;
  onClose: () => void;
  onStarted: () => void | Promise<void>;
}) {
  const [choices, setChoices] = useState<CognifyChoices>({ budget: '', selection: 'all', percent: '20', maxPerDoc: '' });
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState('');
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState('');
  const latest = useRef(0);

  const problem = cognifyProblem(choices);
  const url = `/api/knowledge-engines/${kbId}/cognify`;
  const set = (patch: Partial<CognifyChoices>) => setChoices((c) => ({ ...c, ...patch }));

  useEffect(() => {
    if (!open || problem) return;
    const mine = ++latest.current;
    setEstimating(true);
    const timer = setTimeout(async () => {
      const res = await apiFetch<Estimate>(url, {
        method: 'POST',
        body: JSON.stringify({ ...cognifyBody(choices), dry_run: true }),
        throwOnError: false,
        silent: true,
      });
      if (mine !== latest.current) return;
      setEstimating(false);
      setEstimate(res.data);
      setEstimateError(res.data ? '' : res.error || 'The cost could not be estimated.');
    }, 300);
    return () => clearTimeout(timer);
  }, [open, url, choices, problem]);

  const start = async () => {
    setStarting(true);
    setStartError('');
    const res = await apiFetch(url, {
      method: 'POST',
      body: JSON.stringify(cognifyBody(choices)),
      throwOnError: false,
      silent: true,
    });
    setStarting(false);
    if (res.error) {
      setStartError(res.error);
      return;
    }
    onClose();
    await onStarted();
  };

  const budget = choices.budget.trim() ? Number(choices.budget) : estimate?.max_cost_usd;

  return (
    <ResponsiveModal open={open} onClose={onClose} title="Run Cognify" icon={<Sparkles className="w-4 h-4 text-cyan-400" />} maxWidth="max-w-md">
      <div className="space-y-4" data-testid="cognify-dialog">
        <p className="text-xs text-slate-400">Reads your documents with a model and builds the knowledge graph in the background. You pay the model for each chunk it reads.</p>
        <div>
          <label htmlFor="cognify-selection" className="block text-xs text-slate-400 mb-1.5">Which chunks to read</label>
          <select id="cognify-selection" data-testid="cognify-selection" className={FIELD} value={choices.selection} onChange={(e) => set({ selection: e.target.value as CognifyChoices['selection'] })}>
            <option value="all">All chunks</option>
            <option value="sample">A sample</option>
            <option value="salient">The most useful chunks</option>
          </select>
          <p className="text-[11px] text-slate-500 mt-1">{SELECTION_HELP[choices.selection]}</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {choices.selection !== 'all' && (
            <div>
              <label htmlFor="cognify-percent" className="block text-xs text-slate-400 mb-1.5">Share of chunks (%)</label>
              <input id="cognify-percent" data-testid="cognify-percent" inputMode="decimal" className={FIELD} value={choices.percent} onChange={(e) => set({ percent: e.target.value })} />
            </div>
          )}
          <div>
            <label htmlFor="cognify-max-per-doc" className="block text-xs text-slate-400 mb-1.5">Most chunks per document</label>
            <input id="cognify-max-per-doc" data-testid="cognify-max-per-doc" inputMode="numeric" placeholder="No limit" className={FIELD} value={choices.maxPerDoc} onChange={(e) => set({ maxPerDoc: e.target.value })} />
          </div>
          <div>
            <label htmlFor="cognify-job-budget" className="block text-xs text-slate-400 mb-1.5">Budget for this job ($)</label>
            <input id="cognify-job-budget" data-testid="cognify-job-budget" inputMode="decimal" placeholder={estimate ? estimate.max_cost_usd.toFixed(2) : 'Default'} className={FIELD} value={choices.budget} onChange={(e) => set({ budget: e.target.value })} />
          </div>
        </div>
        {problem && <p role="alert" className="text-xs text-rose-300">{problem}</p>}
        {!problem && (
          <div className="rounded-lg bg-slate-900/50 px-3 py-2 text-xs" data-testid="cognify-estimate">
            {estimating && !estimate && (
              <p className="text-slate-500 flex items-center gap-2"><Loader2 className="w-3 h-3 animate-spin" /> Working out the cost…</p>
            )}
            {estimateError && <p className="text-amber-300">{estimateError}</p>}
            {estimate && !estimateError && (
              <>
                <p className="text-white">
                  About ${estimate.estimated_usd.toFixed(2)} to read {estimate.chunks.toLocaleString()} of {estimate.chunks_total.toLocaleString()} chunks in {estimate.documents.toLocaleString()} document{estimate.documents === 1 ? '' : 's'}.
                </p>
                <p className="text-slate-500 mt-0.5">Model {estimate.model}. {estimate.note}</p>
                {budget !== undefined && estimate.estimated_usd > budget && (
                  <p className="text-amber-300 mt-1" data-testid="cognify-over-budget">This is more than the budget, so the job stops at ${budget.toFixed(2)} and keeps what it has read.</p>
                )}
              </>
            )}
          </div>
        )}
        {startError && <p role="alert" data-testid="cognify-error" className="text-xs text-red-300">{startError}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">Cancel</button>
          <button
            onClick={start}
            disabled={starting || !!problem}
            data-testid="cognify-start"
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-emerald-500 to-cyan-600 text-white text-sm font-medium rounded-lg hover:opacity-90 disabled:opacity-50"
          >
            {starting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Start
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}
