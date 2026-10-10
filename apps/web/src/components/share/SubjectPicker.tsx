'use client';

import { useApi } from '@/hooks/useApi';

interface Member { id: string; email: string; full_name?: string | null }
interface AgentRow { id: string; name: string }

export function useSubjectNames() {
  const { data: team } = useApi<{ members: Member[] }>('/api/team/members');
  const { data: agents } = useApi<AgentRow[]>('/api/agents?limit=100&sort=name');
  const names: Record<string, string> = {};
  for (const m of team?.members || []) names[m.id] = m.full_name ? `${m.full_name} (${m.email})` : m.email;
  for (const a of agents || []) names[a.id] = a.name;
  return { names, members: team?.members || [], agents: agents || [] };
}

/** Pick a person or an agent by name instead of pasting an id. */
export default function SubjectPicker({
  kind, value, onChange, exclude = [], testId,
}: {
  kind: 'user' | 'agent';
  value: string;
  onChange: (id: string) => void;
  exclude?: string[];
  testId?: string;
}) {
  const { members, agents } = useSubjectNames();
  const skip = new Set(exclude);
  const options = kind === 'user'
    ? members.filter((m) => !skip.has(m.id)).map((m) => ({ id: m.id, label: m.full_name ? `${m.full_name} · ${m.email}` : m.email }))
    : agents.filter((a) => !skip.has(a.id)).map((a) => ({ id: a.id, label: a.name }));
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={kind === 'user' ? 'Person' : 'Agent'}
      data-testid={testId}
      className="flex-1 min-w-0 bg-slate-800/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
    >
      <option value="">{kind === 'user' ? 'Choose a person…' : 'Choose an agent…'}</option>
      {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
    </select>
  );
}
