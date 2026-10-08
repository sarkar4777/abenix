'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Loader2, Milestone } from 'lucide-react';
import LevelPill from './LevelPill';
import EnrolWizard from './EnrolWizard';
import { useCapability } from '@/lib/capabilities';
import { autonomyApi, type EnrolTool, type GrantRow } from '@/lib/autonomy';

// The agent's tools that change something, with their autonomy level.
export default function AgentActionsPanel({ agentId, agentName }: { agentId: string; agentName: string }) {
  const { allowed: canView, loading: permLoading } = useCapability('autonomy.view');
  const { allowed: canManage } = useCapability('autonomy.manage');
  const [tools, setTools] = useState<EnrolTool[] | null>(null);
  const [grants, setGrants] = useState<GrantRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [enrolTool, setEnrolTool] = useState<string | null>(null);
  const [wizard, setWizard] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    if (canManage) {
      const r = await autonomyApi.enrolOptions(agentId);
      if (r.error) setError(r.error);
      else setTools(r.data?.tools || []);
      return;
    }
    const r = await autonomyApi.overview();
    if (r.error) setError(r.error);
    else setGrants((r.data?.grants || []).filter((g) => g.agent?.id === agentId));
  }, [agentId, canManage]);

  useEffect(() => {
    if (!permLoading && canView) load();
  }, [permLoading, canView, load]);

  if (permLoading || !canView) return null;

  // one row per enrolled action, a tool with none gets an Enrol row
  type Row = { key: string; label: string; tool: string; grant: GrantRow | null };
  const rows: Row[] = tools
    ? tools.flatMap((t): Row[] => {
      const held = t.grants || (t.grant ? [t.grant] : []);
      return held.length
        ? held.map((g) => ({ key: g.id, label: g.action_type.label, tool: t.tool_name, grant: g }))
        : [{ key: t.tool_name, label: t.effect?.label || t.tool_name, tool: t.tool_name, grant: null }];
    })
    : (grants || []).map((g) => ({ key: g.id, label: g.action_type.label, tool: g.action_type.key, grant: g }));
  const loading = tools === null && grants === null && !error;

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" data-testid="autonomy-agent-actions">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold text-white">
        <Milestone className="h-4 w-4 text-cyan-400" /> Actions
      </h3>
      <p className="mb-3 text-[11px] text-slate-500">Tools that change something, and how much this agent may do on its own.</p>
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading</div>
      ) : error ? (
        <div className="text-xs text-rose-300" role="alert">
          Could not load actions: {error} <button type="button" onClick={load} className="underline">Try again</button>
        </div>
      ) : rows.length === 0 ? (
        <p className="text-xs text-slate-400" data-testid="autonomy-agent-actions-empty">
          {tools ? 'This agent has no tools that change anything.' : 'None of this agent’s actions are enrolled yet.'}
        </p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.key} className="rounded-lg bg-slate-900/30 p-2" data-testid={`autonomy-agent-action-${r.tool}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-xs text-white" title={r.tool}>{r.label}</span>
                {r.grant ? (
                  <Link href={`/autonomy/${r.grant.id}`} className="text-[11px] text-cyan-300 hover:underline">Open</Link>
                ) : canManage ? (
                  <button type="button" onClick={() => { setEnrolTool(r.tool); setWizard(true); }} className="rounded bg-cyan-500/15 px-2 py-0.5 text-[11px] font-medium text-cyan-300 hover:bg-cyan-500/25" data-testid="autonomy-agent-enrol">
                    Enrol
                  </button>
                ) : null}
              </div>
              <div className="mt-1">
                {r.grant ? <LevelPill level={r.grant.level} ceiling={r.grant.ceiling} size="sm" /> : <span className="text-[10px] text-slate-500">Not enrolled, runs as before</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {!canManage && !loading && !error && (
        <p className="mt-3 text-[10px] text-slate-500">Enrolling needs the autonomy.manage permission. <Link href="/admin/permissions" className="text-cyan-300 hover:underline">Permissions</Link></p>
      )}
      <EnrolWizard open={wizard} onClose={() => setWizard(false)} presetAgent={{ id: agentId, name: agentName }} presetTool={enrolTool} onEnrolled={() => load()} />
    </div>
  );
}
