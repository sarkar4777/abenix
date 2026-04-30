'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle,
  CheckSquare,
  Loader2,
  RefreshCw,
  Square,
  Trash2,
} from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';

interface Agent {
  id: string;
  name: string;
  description: string;
  status: string;
  type: string;
  created_at: string;
}

export default function ManageAgentsPage() {
  usePageTitle('Manage Agents');

  const {
    data: agents,
    isLoading: loading,
    mutate: mutateAgents,
  } = useApi<Agent[]>('/api/agents?limit=100');

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [confirmBulk, setConfirmBulk] = useState(false);

  const agentList = agents ?? [];

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selected.size === agentList.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(agentList.map((a) => a.id)));
    }
  };

  const handleBulkDelete = async () => {
    if (selected.size === 0) return;
    setBulkDeleting(true);
    try {
      const res = await apiFetch<{ deleted: number; requested: number }>(
        '/api/agents/bulk',
        {
          method: 'DELETE',
          body: JSON.stringify({ ids: Array.from(selected) }),
        },
      );
      if (res.data) {
        toastSuccess(
          `Deleted ${res.data.deleted} agent${res.data.deleted === 1 ? '' : 's'}`,
        );
        setSelected(new Set());
        setConfirmBulk(false);
        mutateAgents();
      } else {
        toastError('Bulk delete failed', res.error ?? undefined);
      }
    } catch {
      toastError('Failed to delete agents');
    } finally {
      setBulkDeleting(false);
    }
  };

  const formatDate = (iso: string) => {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  if (loading) {
    return (
      <div className="space-y-6 max-w-3xl">
        <div>
          <div className="h-7 w-40 bg-slate-800 animate-pulse rounded" />
          <div className="h-3 w-64 bg-slate-700/50 animate-pulse rounded mt-2" />
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="flex items-center gap-4 px-4 py-3 border-b border-slate-700/30"
            >
              <div className="w-4 h-4 bg-slate-700 animate-pulse rounded" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-32 bg-slate-800 animate-pulse rounded" />
                <div className="h-3 w-48 bg-slate-700/50 animate-pulse rounded" />
              </div>
              <div className="h-5 w-16 bg-slate-800 animate-pulse rounded-full" />
              <div className="h-5 w-14 bg-slate-800 animate-pulse rounded-full" />
              <div className="h-3 w-20 bg-slate-700/50 animate-pulse rounded" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-3xl"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Manage Agents</h1>
          <p className="text-sm text-slate-500 mt-1">
            Select and perform bulk operations on your agents
          </p>
        </div>
        <button
          onClick={() => mutateAgents()}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-2 bg-slate-800/50 border border-slate-700/50 text-sm text-slate-300 rounded-lg hover:text-white hover:bg-slate-800 transition-colors disabled:opacity-50"
        >
          <RefreshCw
            className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`}
          />
          Refresh
        </button>
      </div>

      {/* Bulk Actions Bar */}
      <AnimatePresence>
        {selected.size > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-3 rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3"
          >
            <span className="text-sm text-cyan-300">
              {selected.size} selected
            </span>
            <div className="flex-1" />
            {!confirmBulk ? (
              <button
                onClick={() => setConfirmBulk(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600/20 border border-red-500/30 text-xs text-red-300 hover:bg-red-600/30 transition-colors"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Delete Selected
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-xs text-red-300 flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Confirm delete {selected.size} agent
                  {selected.size === 1 ? '' : 's'}?
                </span>
                <button
                  onClick={handleBulkDelete}
                  disabled={bulkDeleting}
                  className="px-3 py-1.5 rounded-lg bg-red-600 text-xs text-white font-medium hover:bg-red-500 disabled:opacity-50 transition-colors flex items-center gap-1.5"
                >
                  {bulkDeleting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    'Yes, Delete'
                  )}
                </button>
                <button
                  onClick={() => setConfirmBulk(false)}
                  className="px-3 py-1.5 rounded-lg bg-slate-700 text-xs text-slate-300 hover:bg-slate-600 transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Agent Table */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="w-10 py-3 px-4">
                <button
                  onClick={selectAll}
                  className="text-slate-400 hover:text-white transition-colors"
                >
                  {selected.size === agentList.length && agentList.length > 0 ? (
                    <CheckSquare className="w-4 h-4 text-cyan-400" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
              </th>
              <th className="text-left py-3 px-4 text-xs text-slate-500 font-medium uppercase tracking-wider">
                Name
              </th>
              <th className="text-left py-3 px-4 text-xs text-slate-500 font-medium uppercase tracking-wider">
                Type
              </th>
              <th className="text-left py-3 px-4 text-xs text-slate-500 font-medium uppercase tracking-wider">
                Status
              </th>
              <th className="text-right py-3 px-4 text-xs text-slate-500 font-medium uppercase tracking-wider">
                Created
              </th>
            </tr>
          </thead>
          <tbody>
            {agentList.map((agent) => (
              <tr
                key={agent.id}
                className={`border-b border-slate-700/30 hover:bg-slate-700/20 cursor-pointer transition-colors ${
                  selected.has(agent.id) ? 'bg-cyan-500/5' : ''
                }`}
                onClick={() => toggleSelect(agent.id)}
              >
                <td className="py-3 px-4">
                  {selected.has(agent.id) ? (
                    <CheckSquare className="w-4 h-4 text-cyan-400" />
                  ) : (
                    <Square className="w-4 h-4 text-slate-500" />
                  )}
                </td>
                <td className="py-3 px-4">
                  <div>
                    <span className="text-white font-medium">{agent.name}</span>
                    {agent.description && (
                      <p className="text-xs text-slate-500 mt-0.5 truncate max-w-xs">
                        {agent.description}
                      </p>
                    )}
                  </div>
                </td>
                <td className="py-3 px-4">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      agent.type === 'pipeline'
                        ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
                        : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                    }`}
                  >
                    {agent.type}
                  </span>
                </td>
                <td className="py-3 px-4">
                  <span
                    className={`text-xs px-2 py-0.5 rounded-full ${
                      agent.status === 'active'
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                    }`}
                  >
                    {agent.status}
                  </span>
                </td>
                <td className="py-3 px-4 text-right text-xs text-slate-400">
                  {agent.created_at ? formatDate(agent.created_at) : '-'}
                </td>
              </tr>
            ))}
            {agentList.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="py-12 text-center text-sm text-slate-500"
                >
                  No agents found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}
