'use client';

import Link from 'next/link';
import { AlertTriangle, ShieldCheck } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { TIER_STYLE, type Tier, type TierRow } from './TierPolicies';

const TIERS: Tier[] = ['low', 'medium', 'high', 'critical'];
const RANK: Record<Tier, number> = { low: 0, medium: 1, high: 2, critical: 3 };
const ACTION_TEXT = {
  allow: 'runs, and the run is recorded at that tier',
  approval: 'waits for a person to approve it on the Approvals page',
  block: 'is refused',
} as const;

function modelAllowed(allowed: string[], model: string) {
  if (!allowed.length) return true;
  const m = model.toLowerCase();
  return allowed.some((a) => m === a.toLowerCase() || (a.endsWith('*') && m.startsWith(a.slice(0, -1).toLowerCase())));
}

export default function RiskTierPicker({
  value,
  onChange,
  selectedTools,
  hasOutputSchema,
  model,
  isPipeline = false,
}: {
  value?: string;
  onChange: (tier: Tier) => void;
  selectedTools: string[];
  hasOutputSchema: boolean;
  model?: string;
  isPipeline?: boolean;
}) {
  const tier: Tier = (TIERS as string[]).includes(value || '') ? (value as Tier) : 'low';
  const { data } = useApi<{ tiers: TierRow[]; tools: { tool: string; tier: Tier }[] }>('/api/governance/risk');
  const row = data?.tiers.find((t) => t.tier === tier);
  const toolTier = new Map((data?.tools || []).map((t) => [t.tool, t.tier]));
  const above = selectedTools
    .map((t) => ({ tool: t, tier: toolTier.get(t) }))
    .filter((t): t is { tool: string; tier: Tier } => !!t.tier && RANK[t.tier] > RANK[tier]);
  const policyFor = (t: Tier) => data?.tiers.find((x) => x.tier === t)?.effective;
  const needsSchema = !!row?.effective.require_output_schema && !hasOutputSchema;
  const modelBlocked = !isPipeline && !!model && !!row && !modelAllowed(row.effective.allowed_models, model);
  const what = isPipeline ? 'pipeline' : 'agent';

  return (
    <div className="border-t border-slate-700/50 pt-4" data-testid="risk-tier-picker">
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs text-slate-400" id="risk-tier-label">Risk tier</label>
        <Link href="/admin/risk" className="text-[10px] text-cyan-400 hover:underline">What each tier requires</Link>
      </div>
      <div className="grid grid-cols-4 gap-1 p-0.5 rounded-lg border border-slate-700 bg-slate-900/60" role="radiogroup" aria-labelledby="risk-tier-label">
        {TIERS.map((t) => (
          <button
            key={t}
            type="button"
            role="radio"
            aria-checked={tier === t}
            onClick={() => onChange(t)}
            className={`flex items-center justify-center gap-1.5 py-1.5 rounded-md text-xs transition ${
              tier === t ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'
            }`}
            data-testid={`risk-tier-${t}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${TIER_STYLE[t].dot}`} aria-hidden /> {TIER_STYLE[t].label}
          </button>
        ))}
      </div>
      {row && <p className="text-[10px] text-slate-500 mt-1.5">{row.guide}</p>}

      {row && (
        <ul className="mt-2 space-y-1 text-[11px]" data-testid="risk-tier-effects">
          {row.effective.publish_approvals.min_approvers > 0 && (
            <li className="flex gap-1.5 text-slate-300">
              <ShieldCheck className="w-3.5 h-3.5 text-cyan-400 shrink-0 mt-px" />
              New versions need {row.effective.publish_approvals.min_approvers} sign-off
              {row.effective.publish_approvals.min_approvers > 1 ? 's' : ''}
              {row.effective.publish_approvals.exclude_author ? ' from someone other than the author' : ''}.
            </li>
          )}
          {needsSchema && (
            <li className="flex gap-1.5 text-amber-300" data-testid="risk-tier-needs-schema">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
              This tier needs an output schema before the {what} can go live. Add one under Advanced.
            </li>
          )}
          {modelBlocked && (
            <li className="flex gap-1.5 text-amber-300" data-testid="risk-tier-model-blocked">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
              {model} is not allowed at this tier. Allowed: {row.effective.allowed_models.join(', ')}.
            </li>
          )}
          {above.map((t) => {
            const action = policyFor(t.tier)?.tool_call_action || 'allow';
            return (
              <li key={t.tool} className={`flex gap-1.5 ${action === 'block' ? 'text-rose-300' : action === 'approval' ? 'text-amber-300' : 'text-slate-300'}`}>
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
                <span>
                  <code className="font-mono">{t.tool}</code> is {t.tier} risk. Each call {ACTION_TEXT[action]}.
                  {action !== 'allow' && ` Set the tier to ${TIER_STYLE[t.tier].label} if this ${what} should use it freely.`}
                </span>
              </li>
            );
          })}
          {!needsSchema && !modelBlocked && above.length === 0 && row.effective.publish_approvals.min_approvers === 0 && (
            <li className="text-slate-500">Nothing extra is required at this tier.</li>
          )}
        </ul>
      )}
    </div>
  );
}
