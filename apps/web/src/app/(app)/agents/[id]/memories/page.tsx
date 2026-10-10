'use client';

import { useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Brain, Database, Search, Trash2, RefreshCw,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import { toastSuccess, toastError } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';

interface Memory {
  id: string;
  key: string;
  value: string | null;
  memory_type: string;
  importance: number | null;
  access_count: number;
  created_at: string | null;
  updated_at: string | null;
}

const TYPE_COLORS: Record<string, string> = {
  factual: 'bg-cyan-500/10 text-cyan-400',
  procedural: 'bg-purple-500/10 text-purple-400',
  episodic: 'bg-amber-500/10 text-amber-400',
};

export default function AgentMemoriesPage() {
  const params = useParams();
  const agentId = params.id as string;
  usePageTitle('Agent Memories');
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const queryParams = new URLSearchParams();
  queryParams.set('limit', '100');
  if (search) queryParams.set('search', search);
  if (typeFilter) queryParams.set('memory_type', typeFilter);

  const { data: memories, mutate, isLoading, error: loadError } = useApi<Memory[]>(
    agentId ? `/api/agents/${agentId}/memories?${queryParams.toString()}` : null,
  );

  const deleteMemory = useCallback(async (mem: Memory) => {
    if (!confirm(`Delete the memory "${mem.key}"? The agent will no longer recall it.`)) return;
    const r = await apiFetch(`/api/agents/${agentId}/memories/${mem.id}`, { method: 'DELETE', throwOnError: false });
    if (r.error) { toastError('Could not delete the memory', r.error); return; }
    toastSuccess('Memory deleted', mem.key);
    mutate();
  }, [agentId, mutate]);

  const clearAll = useCallback(async () => {
    if (!confirm('Delete every memory this agent saved? This cannot be undone.')) return;
    const r = await apiFetch<{ deleted_count: number }>(`/api/agents/${agentId}/memories?all=true`, { method: 'DELETE', throwOnError: false });
    if (r.error) { toastError('Could not clear memories', r.error); return; }
    const n = r.data?.deleted_count ?? 0;
    toastSuccess('All memories cleared', `${n} deleted`);
    mutate();
  }, [agentId, mutate]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <PageHeader
        title="Agent Memory Store"
        icon={Brain}
        iconClassName="text-purple-400"
        purpose="See and remove the facts this agent saved for itself between runs. For the agent's owner."
        back={{ href: `/agents/${agentId}/info`, label: 'Back to agent' }}
        primaryAction={{ label: 'Refresh', onClick: () => mutate(), icon: RefreshCw }}
        secondaryAction={
          memories && memories.length > 0 ? (
            <button
              onClick={clearAll}
              data-testid="memories-clear-all"
              className="inline-flex min-h-[40px] items-center justify-center gap-1.5 px-3 py-1.5 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              Clear All
            </button>
          ) : undefined
        }
        steps={[
          'An agent with the memory tools saves facts while it runs and recalls them next time.',
          'Search or filter by kind to find a memory.',
          'Delete one that is wrong or out of date, or clear them all to start fresh.',
        ]}
        storageKey="agent-memories"
        className="mb-6"
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="relative flex-1 min-w-0 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search memories"
            data-testid="memories-search"
            placeholder="Search memories..."
            className="w-full pl-9 pr-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div className="flex gap-1">
          {['factual', 'procedural', 'episodic'].map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(typeFilter === t ? null : t)}
              className={`px-3 py-1.5 text-xs rounded-lg border transition-colors ${
                typeFilter === t
                  ? `${TYPE_COLORS[t]} border-current`
                  : 'text-slate-400 border-slate-700 hover:border-slate-600'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Memory list */}
      <div className="space-y-2">
        {isLoading && !memories && (
          <div className="text-center py-10 text-sm text-slate-500" data-testid="memories-loading">Loading memories…</div>
        )}
        {loadError && (
          <div role="alert" className="rounded-xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
            Could not load memories. {loadError}
          </div>
        )}
        {!isLoading && !loadError && memories && memories.length === 0 && (
          <div className="text-center py-16 bg-slate-800/30 border border-slate-700/50 rounded-xl">
            <Database className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white mb-1" data-testid="memories-empty">{search || typeFilter ? 'Nothing matches' : 'No memories stored'}</h3>
            <p className="text-sm text-slate-500 px-4">
              {search || typeFilter
                ? 'Try another word or clear the filter.'
                : 'Memories appear here when this agent has the memory tools and saves something while it runs.'}
            </p>
          </div>
        )}

        {(memories || []).map((mem) => (
          <div
            key={mem.id}
            data-testid="memory-row"
            data-key={mem.key}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4"
          >
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <code className="text-sm font-mono text-cyan-400 font-medium break-all">{mem.key}</code>
                  <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${TYPE_COLORS[mem.memory_type] || 'bg-slate-700 text-slate-400'}`}>
                    {mem.memory_type}
                  </span>
                  {mem.importance != null && (
                    <span className="text-[9px] text-amber-400">
                      importance: {mem.importance.toFixed(1)}
                    </span>
                  )}
                  <span className="text-[9px] text-slate-600">
                    accessed {mem.access_count}x
                  </span>
                </div>
                <p className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">
                  {mem.value || '(empty)'}
                </p>
                <p className="text-[9px] text-slate-600 mt-1">
                  Created: {mem.created_at ? new Date(mem.created_at).toLocaleString() : '--'}
                  {mem.updated_at && ` | Updated: ${new Date(mem.updated_at).toLocaleString()}`}
                </p>
              </div>
              <button
                onClick={() => deleteMemory(mem)}
                aria-label={`Delete memory ${mem.key}`}
                data-testid="memory-delete"
                className="p-1.5 text-slate-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors shrink-0"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  );
}
