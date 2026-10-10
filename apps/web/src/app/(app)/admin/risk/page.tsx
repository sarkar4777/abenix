'use client';

import { useEffect, useRef, useState } from 'react';
import { FileCheck2, Layers, OctagonX, ShieldAlert, Wrench } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { apiFetch } from '@/lib/api-client';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import { holds, useMyPermissions } from '@/lib/capabilities';
import TierPolicies, { type TierRow } from '@/components/governance/TierPolicies';
import KillSwitches from '@/components/governance/KillSwitches';
import ToolTiers from '@/components/governance/ToolTiers';
import AuditIntegrity from '@/components/governance/AuditIntegrity';
import SoleOperatorSetting from '@/components/governance/SoleOperatorSetting';

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

  // counts toward the onboarding journey, once per visit
  const seenSent = useRef(false);
  useEffect(() => {
    if (!canView || !data || seenSent.current) return;
    seenSent.current = true;
    apiFetch('/api/me/journey/seen', {
      method: 'POST',
      body: JSON.stringify({ step: 'risk' }),
      silent: true,
      throwOnError: false,
    }).catch(() => {});
  }, [canView, data]);

  function pick(t: Tab) {
    setTab(t);
    history.replaceState(null, '', `#${t}`);
  }

  if (permsLoading && !perms) {
    return <div className="max-w-6xl mx-auto px-6 py-8"><div className="h-40 rounded-xl bg-slate-800/40 animate-pulse" /></div>;
  }
  if (!canView) {
    return (
      <NoAccess
        testId="risk-no-access"
        title="Risk and Controls"
        purpose="Decide what each risk tier needs before an agent acts, stop anything that misbehaves, and prove the activity log is untouched. For admins and risk owners."
        icon={ShieldAlert}
        need={{ capability: 'risk.view', label: 'View risk and controls' }}
        role={perms?.role}
        instead={{ text: 'Approvals lists any agent action waiting for a decision from you.', href: '/approvals', label: 'Open Approvals' }}
      />
    );
  }

  const activeCount = (switches?.switches || []).filter((x) => x.active).length;

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <PageHeader
        className="mb-6"
        title="Risk and Controls"
        purpose="Decide what each risk tier needs before an agent acts, stop anything that misbehaves, and prove the activity log is untouched. For admins and risk owners."
        icon={ShieldAlert}
        storageKey="admin-risk"
        docSlug="08-howto/11-governance"
        primaryAction={holds(caps, 'killswitch.manage') ? { label: 'Open kill switches', icon: OctagonX, onClick: () => pick('switches'), testId: 'risk-open-switches' } : undefined}
        steps={[
          'Tier policies set what each risk tier needs, such as sign-offs before a new version goes live or a person approving a risky tool call.',
          'Kill switches stop an agent, a tool or everything at once, straight away.',
          'Tool tiers show which risk tier each tool falls in.',
          'Audit integrity checks that no one has changed the activity log. Every change here is recorded there too.',
        ]}
      />

      {!holds(caps, 'risk.manage') && (
        <ViewOnlyBanner testId="risk-view-only">
          You can see what each risk tier needs, which kill switches are on and whether the activity log is intact. Admins and risk owners change them. Ask an admin for Manage risk if you own a risk area.
        </ViewOnlyBanner>
      )}

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
            {tab === 'tiers' && (
              <>
                <SoleOperatorSetting canChange={!!perms?.is_admin} />
                <TierPolicies tiers={data.tiers} canManage={holds(caps, 'risk.manage')} onSaved={mutate} />
              </>
            )}
            {tab === 'switches' && <KillSwitches canManage={holds(caps, 'killswitch.manage')} tools={data.tools} />}
            {tab === 'tools' && <ToolTiers tools={data.tools} />}
            {tab === 'audit' && <AuditIntegrity canVerify={holds(caps, 'audit.verify')} canExport={holds(caps, 'audit.view')} />}
          </>
        ) : null}
      </div>
    </div>
  );
}
