'use client';

import { useEffect, useState } from 'react';
import { FileCheck2, Layers, OctagonX, ShieldAlert, Wrench } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { holds, useMyPermissions } from '@/lib/capabilities';
import TierPolicies, { type TierRow } from '@/components/governance/TierPolicies';
import KillSwitches from '@/components/governance/KillSwitches';
import ToolTiers from '@/components/governance/ToolTiers';
import AuditIntegrity from '@/components/governance/AuditIntegrity';

type Tab = 'tiers' | 'switches' | 'tools' | 'audit';

const TABS: { id: Tab; label: string; icon: typeof Layers }[] = [
  { id: 'tiers', label: 'Tier policies', icon: Layers },
  { id: 'switches', label: 'Kill switches', icon: OctagonX },
  { id: 'tools', label: 'Tool tiers', icon: Wrench },
  { id: 'audit', label: 'Audit integrity', icon: FileCheck2 },
];

interface Overview {
  tiers: TierRow[];
  tools: { tool: string; tier: string }[];
}

export default function RiskPage() {
  const { perms, loading: permsLoading } = useMyPermissions();
  const caps = perms?.capabilities;
  const canView = holds(caps, 'risk.view');
  const { data, error, isLoading, mutate } = useApi<Overview>(canView ? '/api/governance/risk' : null);
  const [tab, setTab] = useState<Tab>('tiers');
  const { data: switches } = useApi<{ switches: { active: boolean }[] }>(
    canView ? '/api/governance/kill-switches' : null,
  );

  useEffect(() => {
    const fromHash = window.location.hash.replace('#', '') as Tab;
    if (TABS.some((t) => t.id === fromHash)) setTab(fromHash);
  }, []);

  function pick(t: Tab) {
    setTab(t);
    history.replaceState(null, '', `#${t}`);
  }

  if (permsLoading && !perms) {
    return <div className="max-w-6xl mx-auto px-6 py-8"><div className="h-40 rounded-xl bg-slate-800/40 animate-pulse" /></div>;
  }
  if (!canView) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-16 text-center" data-testid="risk-no-access">
        <ShieldAlert className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <h1 className="text-xl font-semibold text-white">Risk and Controls</h1>
        <p className="text-slate-400 mt-2">
          This page needs the risk.view capability. An admin can grant it under Admin, Permissions.
        </p>
      </div>
    );
  }

  const activeCount = (switches?.switches || []).filter((x) => x.active).length;

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <header className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <ShieldAlert className="w-6 h-6 text-cyan-400" />
          <h1 className="text-3xl font-semibold text-white">Risk and Controls</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Decide what each risk tier requires, stop anything that misbehaves, and prove the activity log has not been
          touched. Everything here applies to the whole tenant and is recorded in the audit log.
        </p>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-slate-800 mb-6" role="tablist" aria-label="Risk and Controls">
        {TABS.map((t) => {
          const Icon = t.icon;
          const on = tab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={on}
              aria-controls={`panel-${t.id}`}
              onClick={() => pick(t.id)}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 -mb-px transition ${
                on ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white'
              }`}
              data-testid={`risk-tab-${t.id}`}
            >
              <Icon className="w-4 h-4" /> {t.label}
              {t.id === 'switches' && activeCount > 0 && <span className="text-rose-300">{activeCount}</span>}
            </button>
          );
        })}
      </div>

      <div id={`panel-${tab}`} role="tabpanel">
        {error ? (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">{error}</div>
        ) : isLoading && !data ? (
          <div className="space-y-4">
            {[0, 1, 2].map((i) => <div key={i} className="h-40 rounded-xl bg-slate-800/40 animate-pulse" />)}
          </div>
        ) : data ? (
          <>
            {tab === 'tiers' && <TierPolicies tiers={data.tiers} canManage={holds(caps, 'risk.manage')} onSaved={mutate} />}
            {tab === 'switches' && <KillSwitches canManage={holds(caps, 'killswitch.manage')} tools={data.tools} />}
            {tab === 'tools' && <ToolTiers tools={data.tools} />}
            {tab === 'audit' && <AuditIntegrity canVerify={holds(caps, 'audit.verify')} />}
          </>
        ) : null}
      </div>
    </div>
  );
}
