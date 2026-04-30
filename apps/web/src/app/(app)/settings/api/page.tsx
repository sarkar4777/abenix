'use client';

import { motion } from 'framer-motion';
import { Copy, Eye, EyeOff, Key, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

const MOCK_KEYS = [
  { id: '1', name: 'Production API Key', prefix: 'af_prod_****8x2f', created: 'Jan 15, 2026', lastUsed: '2 hours ago' },
  { id: '2', name: 'Development Key', prefix: 'af_dev_****3k9m', created: 'Jan 20, 2026', lastUsed: '5 min ago' },
  { id: '3', name: 'CI/CD Pipeline', prefix: 'af_ci_****7p1n', created: 'Feb 1, 2026', lastUsed: '1 day ago' },
];

export default function APIKeysPage() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-3xl"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">API Keys</h1>
          <p className="text-sm text-slate-500 mt-1">Manage API access to Abenix</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          <Plus className="w-4 h-4" />
          Generate Key
        </button>
      </div>

      <div className="space-y-3">
        {MOCK_KEYS.map((apiKey) => (
          <div
            key={apiKey.id}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 flex items-center gap-4"
          >
            <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
              <Key className="w-5 h-5 text-amber-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white">{apiKey.name}</p>
              <p className="text-xs text-slate-500 font-mono mt-0.5">{apiKey.prefix}</p>
              <p className="text-xs text-slate-600 mt-0.5">
                Created {apiKey.created} · Last used {apiKey.lastUsed}
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors">
                <Copy className="w-4 h-4" />
              </button>
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  );
}
