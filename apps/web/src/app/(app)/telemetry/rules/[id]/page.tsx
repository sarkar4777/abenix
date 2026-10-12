'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import useSWR from 'swr';
import { RefreshCw, Zap } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import FiringHistory from '@/components/telemetry-rules/FiringHistory';
import RuleBuilder from '@/components/telemetry-rules/RuleBuilder';
import { ago, draftFromRule, type Rule } from '@/components/telemetry-rules/lib';
import { Badge, severityTone } from '@/components/telemetry-rules/ui';

function fetcher(url: string) {
  return apiFetch<unknown>(url, { silent: true });
}

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(h);
  }, [ms]);
  return now;
}

export default function RuleRoute() {
  const { id } = useParams<{ id: string }>();
  const { perms, loading } = useMyPermissions();
  const canView = holds(perms?.capabilities, 'telemetry.view');
  const canManage = holds(perms?.capabilities, 'telemetry.manage');
  const now = useNow(10_000);
  const res = useSWR(canView && id ? `/api/telemetry/rules/${encodeURIComponent(id)}` : null, fetcher, { revalidateOnFocus: false });
  const list = useSWR(canView ? '/api/telemetry/rules' : null, fetcher, { revalidateOnFocus: false });
  const rule = (res.data?.data ?? null) as Rule | null;
  usePageTitle(rule ? rule.name : 'Signal rule');
  const initial = useMemo(() => (rule ? draftFromRule(rule) : null), [rule]);
  const others = useMemo(
    () => (Array.isArray(list.data?.data) ? (list.data!.data as Rule[]) : []).filter((r) => r.id !== id).map((r) => r.name),
    [list.data, id],
  );
  const readOnly = !canManage || (rule ? !rule.can_edit : false);
  const purpose = rule?.summary || 'A rule that watches live signals and acts when something happens.';

  if (loading && !perms) return <div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>;
  if (perms && !canView) {
    return (
      <NoAccess
        testId="rule-no-access"
        title="Signal rule"
        purpose={purpose}
        icon={Zap}
        need={{ capability: 'telemetry.view', label: 'View machine telemetry' }}
        role={perms.role}
        instead={{ text: 'Alerts lists anything that went wrong.', href: '/alerts', label: 'Open Alerts' }}
      />
    );
  }
  const missing = res.data?.errorDetail?.code === 404;
  return (
    <div className="mx-auto max-w-7xl space-y-4" data-testid="rule-page">
      <PageHeader
        title={rule?.name || 'Signal rule'}
        purpose={missing ? 'This rule does not exist any more.' : purpose}
        icon={Zap}
        compact
        back={{ href: '/telemetry/rules', label: 'Signal rules' }}
        meta={rule ? (
          <span className="flex flex-wrap items-center gap-1.5">
            <Badge tone={severityTone(rule.severity)}>{rule.severity}</Badge>
            <Badge tone={rule.enabled ? 'emerald' : 'slate'}>{rule.enabled ? 'On' : 'Off'}</Badge>
            {rule.firing_now > 0 && <Badge tone="rose">Firing on {rule.firing_now}</Badge>}
          </span>
        ) : undefined}
      />
      {missing ? (
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-300" data-testid="rule-missing">
          <p>No rule with this link. It may have been deleted.</p>
          <Link href="/telemetry/rules" className="mt-3 inline-flex min-h-[40px] items-center rounded-lg border border-slate-600 px-4 text-slate-200 hover:bg-slate-800">See all rules</Link>
        </div>
      ) : res.data?.error ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-100" role="alert">
          <p>{res.data.error}</p>
          <button type="button" onClick={() => void res.mutate()} className="mt-2 inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-600 px-3 text-xs text-slate-200 hover:bg-slate-800">
            <RefreshCw className="h-3.5 w-3.5" /> Try again
          </button>
        </div>
      ) : !rule || !initial ? (
        <div className="h-64 animate-pulse rounded-xl bg-slate-800/40" data-testid="rule-loading" />
      ) : (
        <>
          {readOnly && (
            <ViewOnlyBanner testId="rule-view-only">
              {canManage
                ? 'This rule belongs to a team you are not part of, so only an admin can change it.'
                : 'You can see this rule and what it did. An admin, or anyone with Manage telemetry, can change it.'}
            </ViewOnlyBanner>
          )}
          <p className="text-xs text-slate-400" data-testid="rule-stats">
            {rule.fire_count
              ? `Fired ${rule.fire_count.toLocaleString('en-US')} ${rule.fire_count === 1 ? 'time' : 'times'}, last ${ago(rule.last_fired_at, now)}.`
              : 'It has not fired yet.'}
            {rule.updated_at ? ` Changed ${ago(rule.updated_at, now)}.` : ''}
          </p>
          <RuleBuilder
            initial={initial}
            ruleId={rule.id}
            readOnly={readOnly}
            otherNames={others}
            onSaved={() => { void res.mutate(); void list.mutate(); }}
          />
          <section className="space-y-3" data-testid="rule-history">
            <h2 className="text-sm font-semibold text-white">Firing history</h2>
            <FiringHistory ruleId={rule.id} now={now} emptyHint="This rule has not fired yet. Each firing, and what every step did, shows here." />
          </section>
        </>
      )}
    </div>
  );
}
