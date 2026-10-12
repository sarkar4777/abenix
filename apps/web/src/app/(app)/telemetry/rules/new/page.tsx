'use client';

import { Suspense, useMemo } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import useSWR from 'swr';
import { Zap } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import RuleBuilder from '@/components/telemetry-rules/RuleBuilder';
import { TEMPLATES, blankDraft, type Rule, type RuleDraft } from '@/components/telemetry-rules/lib';

const PURPOSE = 'Pick what to watch, say when it should fire and what should happen. The rule is replayed over the last hour before you save it.';

function fetcher(url: string) {
  return apiFetch<Rule[]>(url, { silent: true });
}

function NewRule() {
  usePageTitle('New signal rule');
  const params = useSearchParams();
  const { perms, loading } = useMyPermissions();
  const canView = holds(perms?.capabilities, 'telemetry.view');
  const canManage = holds(perms?.capabilities, 'telemetry.manage');
  const tpl = params.get('template');
  const group = params.get('group');
  const node = params.get('node');
  const device = params.get('device');
  const signal = params.get('signal');
  const runAgent = params.get('run_agent');
  const initial = useMemo<RuleDraft>(() => {
    const d = { ...blankDraft(), ...(TEMPLATES.find((t) => t.id === tpl)?.build() ?? {}) };
    // from an agent made on Telemetry, Agents: the rule runs it
    if (runAgent) d.actions = [{ kind: 'run', agent_id: runAgent, message: '', wait: true }, ...d.actions.filter((a) => a.kind !== 'run')];
    if (group && node) d.scope = { kind: 'asset', group, node, device: device ?? '*' };
    if (signal && d.condition.kind !== 'geofence') d.condition = { ...d.condition, signal };
    return d;
  }, [tpl, group, node, device, signal, runAgent]);
  const list = useSWR(canView ? '/api/telemetry/rules' : null, fetcher, { revalidateOnFocus: false });
  const names = Array.isArray(list.data?.data) ? (list.data!.data as Rule[]).map((r) => r.name) : [];

  if (loading && !perms) return <div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>;
  if (perms && !canView) {
    return (
      <NoAccess
        testId="rule-new-no-access"
        title="New signal rule"
        purpose={PURPOSE}
        icon={Zap}
        need={{ capability: 'telemetry.view', label: 'View machine telemetry' }}
        role={perms.role}
        instead={{ text: 'Alerts lists anything that went wrong.', href: '/alerts', label: 'Open Alerts' }}
      />
    );
  }
  return (
    <div className="mx-auto max-w-7xl space-y-4" data-testid="rule-new-page">
      <PageHeader title="New signal rule" purpose={PURPOSE} icon={Zap} compact back={{ href: '/telemetry/rules', label: 'Signal rules' }} />
      {perms && !canManage ? (
        <ViewOnlyBanner testId="rule-new-view-only">
          Making rules needs Manage telemetry. An admin can grant it under Admin, Permissions.{' '}
          <Link href="/telemetry/rules" className="text-cyan-300 hover:underline">See the rules there are</Link>.
        </ViewOnlyBanner>
      ) : (
        <RuleBuilder initial={initial} otherNames={names} />
      )}
    </div>
  );
}

export default function NewRuleRoute() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>}>
      <NewRule />
    </Suspense>
  );
}
