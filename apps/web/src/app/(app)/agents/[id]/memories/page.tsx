'use client';

import { useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  ArrowLeft, Brain, Database, Search, Trash2, RefreshCw,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { toastSuccess, toastError } from '@/stores/toastStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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

  const { data: memories, mutate } = useApi<Memory[]>(
    agentId ? `/api/agents/${agentId}/memories?${queryParams.toString()}` : null,
  );

  const deleteMemory = useCallback(async (memoryId: string) => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    try {
      await fetch(`${API_URL}/api/agents/${agentId}/memories/${memoryId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      toastSuccess('Memory deleted');
      mutate();
    } catch {
      toastError('Failed to delete memory');
    }
  }, [agentId, mutate]);

  const clearAll = useCallback(async () => {
    if (!confirm('Delete ALL memories for this agent? This cannot be undone.')) return;
    const token = localStorage.getItem('access_token');
    if (!token) return;
    try {
      await fetch(`${API_URL}/api/agents/${agentId}/memories?all=true`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      toastSuccess('All memories cleared');
      mutate();
    } catch {
      toastError('Failed to clear memories');
    }
  }, [agentId, mutate]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <div className="flex items-center gap-3 mb-6">
        <Link
          href={`/agents/${agentId}/info`}
          className="p-2 rounded-lg hover:bg-slate-800/50 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Brain className="w-5 h-5 text-purple-400" />
            Agent Memory Store
          </h1>
          <p className="text-sm text-slate-500">
            Browse and manage persistent memories stored by this agent
          </p>
        </div>
        {memories && memories.length > 0 && (
          <button
            onClick={clearAll}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg hover:bg-red-500/20 transition-colors"
          >
            <Trash2 className="w-3 h-3" />
            Clear All
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
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
        {(!memories || memories.length === 0) && (
          <div className="text-center py-16 bg-slate-800/30 border border-slate-700/50 rounded-xl">
            <Database className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white mb-1">No memories stored</h3>
            <p className="text-sm text-slate-500">
              This agent hasn&apos;t stored any persistent memories yet.
              Memories are created when the agent uses the memory_store tool during execution.
            </p>
          </div>
        )}

        {(memories || []).map((mem) => (
          <div
            key={mem.id}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4"
          >
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <code className="text-sm font-mono text-cyan-400 font-medium">{mem.key}</code>
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
                onClick={() => deleteMemory(mem.id)}
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
