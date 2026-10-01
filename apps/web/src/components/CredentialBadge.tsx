'use client';

import Link from 'next/link';
import { KeyRound } from 'lucide-react';

export type ToolCredentialStatus = 'configured' | 'missing' | 'optional' | 'none';

/** Where a value comes from, highest first. 'tenant' is a row saved for the caller's tenant, 'stored' one saved for the platform. */
export type ToolCredentialSource = 'override' | 'tenant' | 'stored' | 'env' | 'file' | 'default' | 'unset';

export interface ToolConfigField {
  key: string;
  label?: string;
  required: boolean;
  is_set: boolean;
  source: ToolCredentialSource | string;
  tenant_source?: 'tenant' | 'unset';
  platform_source?: ToolCredentialSource | string;
  signup_url?: string;
}

/** The `config` object every row of /api/tools carries. */
export interface ToolConfigInfo {
  status: ToolCredentialStatus;
  fields: ToolConfigField[];
}

export function missingKeys(config?: ToolConfigInfo | null): ToolConfigField[] {
  return (config?.fields || []).filter((f) => !f.is_set);
}

export function adminConfigHref(config?: ToolConfigInfo | null): string {
  const first = missingKeys(config)[0] || config?.fields?.[0];
  return first ? `/admin/tool-config#${first.key}` : '/admin/tool-config';
}

const STYLE: Record<Exclude<ToolCredentialStatus, 'none'>, { cls: string; text: string }> = {
  missing: { cls: 'bg-rose-500/10 text-rose-300 border-rose-500/30', text: 'needs key' },
  optional: { cls: 'bg-amber-500/10 text-amber-300 border-amber-500/30', text: 'optional key' },
  configured: { cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30', text: 'key set' },
};

export function CredentialBadge({
  config,
  compact = false,
}: {
  config?: ToolConfigInfo | null;
  compact?: boolean;
}) {
  if (!config || config.status === 'none') return null;
  const s = STYLE[config.status];
  const missing = missingKeys(config).map((f) => f.key);
  const fromTenant = config.fields.filter((f) => f.source === 'tenant').length;
  const title =
    config.status === 'configured'
      ? `All ${config.fields.length} configured value(s) present${fromTenant ? `, ${fromTenant} saved for this tenant` : ''}`
      : `Not set for this tenant: ${missing.join(', ')}. An admin adds these under Admin -> Tool Configuration.`;
  return (
    <span
      title={title}
      data-testid={`credential-badge-${config.status}`}
      className={`inline-flex items-center gap-1 border rounded px-1.5 ${compact ? 'py-0 text-[9px]' : 'py-0.5 text-[10px]'} uppercase tracking-wider ${s.cls}`}
    >
      <KeyRound className={compact ? 'w-2.5 h-2.5' : 'w-3 h-3'} />
      {s.text}
    </span>
  );
}

/** One line telling the reader what to do about a missing key. */
export function CredentialHint({
  config,
  isAdmin,
}: {
  config?: ToolConfigInfo | null;
  isAdmin: boolean;
}) {
  const missing = missingKeys(config);
  if (!config || config.status === 'none' || !missing.length) return null;
  const keys = missing.map((f) => f.key).join(', ');
  const tone = config.status === 'missing' ? 'text-rose-300/90' : 'text-amber-300/80';
  return (
    <p className={`text-[11px] mt-1.5 ${tone}`} data-testid="credential-hint">
      {config.status === 'missing' ? 'Will not run without ' : 'Runs with reduced sources without '}
      <code className="font-mono">{keys}</code>.{' '}
      {isAdmin ? (
        <Link href={adminConfigHref(config)} className="underline hover:text-white">
          Configure
        </Link>
      ) : (
        <>Ask an admin to add it under Admin -&gt; Tool Configuration.</>
      )}
    </p>
  );
}
