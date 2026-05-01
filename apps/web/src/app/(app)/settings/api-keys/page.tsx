'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, Copy, Key, Loader2, Plus, Trash2, X } from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';

interface ApiKeyData {
  id: string;
  name: string;
  key_prefix: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
  raw_key?: string;
}

export default function ApiKeysPage() {
  usePageTitle('API Keys');
  const {
    data: keys,
    isLoading: loading,
    mutate: mutateKeys,
  } = useApi<ApiKeyData[]>('/api/api-keys');
  const [showCreate, setShowCreate] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState<ApiKeyData | null>(null);
  const [copied, setCopied] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);
    try {
      const res = await apiFetch<ApiKeyData>('/api/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newKeyName.trim() }),
      });
      if (res.data) {
        setNewKey(res.data);
        setNewKeyName('');
        setShowCreate(false);
        mutateKeys();
        toastSuccess('API key created');
      }
    } catch {
      toastError('Failed to create API key');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    setRevoking(keyId);
    try {
      await apiFetch(`/api/api-keys/${keyId}`, { method: 'DELETE' });
      mutateKeys();
      toastSuccess('API key revoked');
    } catch {
      toastError('Failed to revoke API key');
    } finally {
      setRevoking(null);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
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
      <div className="space-y-6 max-w-2xl">
        <div className="flex items-center justify-between">
          <div>
            <div className="h-7 w-24 bg-slate-800 animate-pulse rounded" />
            <div className="h-3 w-48 bg-slate-700/50 animate-pulse rounded mt-2" />
          </div>
          <div className="h-9 w-32 bg-slate-800 animate-pulse rounded-lg" />
        </div>
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg bg-slate-800 animate-pulse shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-28 bg-slate-800 animate-pulse rounded" />
                <div className="h-3 w-20 bg-slate-700/50 animate-pulse rounded" />
                <div className="h-3 w-40 bg-slate-700/50 animate-pulse rounded" />
              </div>
              <div className="w-8 h-8 rounded-lg bg-slate-800 animate-pulse" />
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
      className="space-y-6 max-w-2xl"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">API Keys</h1>
          <p className="text-sm text-slate-500 mt-1">
            Manage API access to Abenix
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          Generate Key
        </button>
      </div>

      <AnimatePresence>
        {newKey?.raw_key && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4"
          >
            <div className="flex items-start justify-between mb-2">
              <p className="text-sm text-emerald-400 font-medium">
                Key created — copy it now, it won&apos;t be shown again
              </p>
              <button
                onClick={() => setNewKey(null)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 bg-slate-900/50 rounded-lg text-xs text-emerald-300 font-mono break-all">
                {newKey.raw_key}
              </code>
              <button
                onClick={() => handleCopy(newKey.raw_key!)}
                className="shrink-0 px-3 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg text-xs text-slate-300 hover:text-white transition-colors flex items-center gap-1.5"
              >
                {copied ? (
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showCreate && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4"
          >
            <p className="text-sm text-white font-medium mb-3">
              Create new API key
            </p>
            <div className="flex items-center gap-3">
              <input
                type="text"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="Key name (e.g. Production)"
                className="flex-1 px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none transition-colors"
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              />
              <button
                onClick={handleCreate}
                disabled={creating || !newKeyName.trim()}
                className="px-4 py-2.5 bg-cyan-500/20 text-cyan-400 text-sm font-medium rounded-lg hover:bg-cyan-500/30 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Create
              </button>
              <button
                onClick={() => {
                  setShowCreate(false);
                  setNewKeyName('');
                }}
                className="px-3 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="space-y-3">
        {(keys ?? []).length === 0 && !showCreate ? (
          <div className="bg-slate-800/30 border border-dashed border-slate-700/50 rounded-xl p-12 text-center">
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 flex items-center justify-center mx-auto mb-3">
              <Key className="w-6 h-6 text-amber-400" />
            </div>
            <p className="text-sm text-slate-400">No API keys yet</p>
            <p className="text-xs text-slate-500 mt-1">
              Generate a key to access the Abenix API
            </p>
          </div>
        ) : (
          (keys ?? []).map((apiKey) => (
            <div
              key={apiKey.id}
              className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 flex items-center gap-4"
            >
              <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
                <Key className="w-5 h-5 text-amber-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white">{apiKey.name}</p>
                <p className="text-xs text-slate-500 font-mono mt-0.5">
                  {apiKey.key_prefix}
                </p>
                <p className="text-xs text-slate-600 mt-0.5">
                  Created {formatDate(apiKey.created_at)}
                  {apiKey.last_used_at &&
                    ` · Last used ${formatDate(apiKey.last_used_at)}`}
                </p>
              </div>
              <button
                onClick={() => handleRevoke(apiKey.id)}
                disabled={revoking === apiKey.id}
                className="w-8 h-8 flex items-center justify-center rounded-lg text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors disabled:opacity-50"
              >
                {revoking === apiKey.id ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Trash2 className="w-4 h-4" />
                )}
              </button>
            </div>
          ))
        )}
      </div>
    </motion.div>
  );
}
