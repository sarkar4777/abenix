'use client';

import { useState } from 'react';
import { Star } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';

interface Fav { agent_id: string }

export function useFavorites() {
  const { data, mutate } = useApi<Fav[]>('/api/agents/favorites');
  return { ids: new Set((data || []).map((f) => f.agent_id)), loaded: data !== undefined, mutate };
}

/** Star an agent so it shows under Starred on the Agents page. */
export default function FavoriteButton({ agentId, agentName, compact = false }: { agentId: string; agentName: string; compact?: boolean }) {
  const { ids, mutate } = useFavorites();
  const [busy, setBusy] = useState(false);
  const on = ids.has(agentId);

  const toggle = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setBusy(true);
    const r = await apiFetch(`/api/agents/${agentId}/favorite`, { method: on ? 'DELETE' : 'POST', throwOnError: false });
    setBusy(false);
    if (r.error) { toastError(on ? 'Could not unstar' : 'Could not star', r.error); return; }
    toastSuccess(on ? 'Removed from starred' : 'Starred', agentName);
    mutate();
  };

  return (
    <button
      onClick={toggle}
      disabled={busy}
      aria-pressed={on}
      aria-label={on ? `Unstar ${agentName}` : `Star ${agentName}`}
      title={on ? 'Starred. Click to remove' : 'Star it to find it quickly'}
      data-testid="agent-favorite"
      data-on={on ? '1' : '0'}
      className={compact
        ? `p-1 rounded hover:bg-slate-700/50 disabled:opacity-50 ${on ? 'text-amber-300' : 'text-slate-500 hover:text-amber-300'}`
        : `flex items-center gap-1.5 px-3 py-2 border text-xs rounded-lg transition-colors disabled:opacity-50 ${on ? 'bg-amber-500/10 border-amber-500/30 text-amber-300' : 'bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-700'}`}
    >
      <Star className={`w-3.5 h-3.5 ${on ? 'fill-current' : ''}`} />
      {!compact && (on ? 'Starred' : 'Star')}
    </button>
  );
}
