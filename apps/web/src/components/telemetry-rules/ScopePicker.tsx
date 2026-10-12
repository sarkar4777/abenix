'use client';

import { useMemo } from 'react';
import Link from 'next/link';
import useSWR from 'swr';
import { apiFetch } from '@/lib/api-client';
import { ASSET_TYPES, type Scope } from './lib';
import { Choice, Field, cls } from './ui';
import { assetLabel, repeatedNames } from '@/lib/telemetry/assetLabel';
import { pluralShown } from '@/lib/plural';

interface AssetRow { key: string; group: string; node: string; device: string; display_name: string | null; type: string | null; tags: string[]; parts?: string[]; online?: boolean | null; live?: boolean }
interface Meta { types?: Record<string, number>; tags?: Array<{ tag: string; count: number }> }

function fetcher(url: string) {
  return apiFetch<AssetRow[]>(url, { silent: true });
}

export function useAssets() {
  const res = useSWR('/api/telemetry/assets?limit=5000', fetcher, { revalidateOnFocus: false, refreshInterval: 60_000 });
  const rows = Array.isArray(res.data?.data) ? (res.data!.data as AssetRow[]) : null;
  const meta = (res.data?.meta ?? {}) as Meta;
  const names = useMemo(() => {
    const m: Record<string, string> = {};
    for (const r of rows || []) if (r.display_name) m[r.key] = r.display_name;
    return m;
  }, [rows]);
  return { rows, meta, names, loading: !res.data && !res.error };
}

const TYPE_LABEL: Record<string, string> = { vehicle: 'Vehicles', machine: 'Machines', sensor: 'Sensors', device: 'Devices', system: 'Systems' };

export default function ScopePicker({
  scope, onChange, errors, disabled,
}: { scope: Scope; onChange: (s: Scope) => void; errors: Record<string, string>; disabled?: boolean }) {
  const { rows, meta, loading } = useAssets();
  const assets = useMemo(() => (rows || []).filter((r) => !r.device), [rows]);
  const groups = useMemo(() => Array.from(new Set(assets.map((a) => a.group))).sort(), [assets]);
  const current = assets.find((a) => a.group === scope.group && a.node === scope.node);
  const typeCounts = meta.types || {};
  const tags = meta.tags || [];
  const matching = useMemo(() => {
    if (scope.kind === 'type') return assets.filter((a) => a.type === scope.type && (!scope.group || a.group === scope.group)).length;
    if (scope.kind === 'tag') return assets.filter((a) => (a.tags || []).includes((scope.tag || '').toLowerCase()) && (!scope.group || a.group === scope.group)).length;
    return 0;
  }, [assets, scope]);

  const repeated = useMemo(() => repeatedNames(assets), [assets]);
  const set = (patch: Partial<Scope>) => onChange({ ...scope, ...patch });

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="What the rule watches">
        <Choice active={scope.kind === 'asset'} disabled={disabled} onClick={() => onChange({ kind: 'asset', group: scope.group || '', node: scope.node || '', device: '*' })} title="One asset" help="A truck, a machine, a sensor or a system" testId="scope-kind-asset" />
        <Choice active={scope.kind === 'type'} disabled={disabled} onClick={() => onChange({ kind: 'type', type: scope.type || '', group: '' })} title="Every asset of a type" help="All vehicles, all machines, and new ones as they arrive" testId="scope-kind-type" />
        <Choice active={scope.kind === 'tag'} disabled={disabled} onClick={() => onChange({ kind: 'tag', tag: scope.tag || '', group: '' })} title="Assets with a tag" help="Like north pit or night shift" testId="scope-kind-tag" />
      </div>

      {scope.kind === 'asset' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Asset" error={errors['scope.node'] || errors['scope.group']} htmlFor="scope-asset" testId="scope-asset-field"
            help={loading ? 'Loading assets' : assets.length ? `${pluralShown(assets.length, (assets.length).toLocaleString('en-US'), 'asset')} are streaming or named.` : undefined}>
            <select
              id="scope-asset"
              value={scope.group && scope.node ? `${scope.group}/${scope.node}` : ''}
              disabled={disabled}
              onChange={(e) => {
                const [g, ...rest] = e.target.value.split('/');
                set({ group: g || '', node: rest.join('/') || '', device: '*' });
              }}
              className={cls(errors['scope.node'])}
              data-testid="scope-asset"
            >
              <option value="">{loading ? 'Loading' : assets.length ? 'Pick an asset' : 'No assets yet'}</option>
              {groups.map((g) => (
                <optgroup key={g} label={g}>
                  {assets.filter((a) => a.group === g).map((a) => (
                    <option key={a.key} value={`${a.group}/${a.node}`}>
                      {assetLabel(a, repeated)}{a.online === false ? ', offline' : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </Field>
          <Field label="Which signals" htmlFor="scope-part" testId="scope-part-field"
            help={scope.device === '*' ? 'Signals of the asset and every part on it.' : scope.device === '' ? 'Only the signals the asset sends itself.' : `Only the signals of part ${scope.device}.`}>
            <select id="scope-part" value={scope.device ?? '*'} disabled={disabled || !current} onChange={(e) => set({ device: e.target.value })} className={cls()} data-testid="scope-part">
              <option value="*">The asset and any of its parts</option>
              <option value="">The asset itself</option>
              {(current?.parts || []).map((p) => <option key={p} value={p}>Part {p}</option>)}
            </select>
          </Field>
          {!loading && assets.length === 0 && (
            <p className="text-xs text-slate-400 sm:col-span-2">
              No asset has streamed yet. <Link href="/telemetry?tab=sources" className="text-cyan-300 hover:underline">Connect a source</Link> first, or watch a type or a tag that new assets will have.
            </p>
          )}
        </div>
      )}

      {scope.kind === 'type' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Asset type" error={errors['scope.type']} htmlFor="scope-type" testId="scope-type-field"
            help={scope.type ? `${matching} ${matching === 1 ? 'asset has' : 'assets have'} this type now.` : 'Types are set on the Assets page.'}>
            <select id="scope-type" value={scope.type || ''} disabled={disabled} onChange={(e) => set({ type: e.target.value })} className={cls(errors['scope.type'])} data-testid="scope-type">
              <option value="">Pick a type</option>
              {ASSET_TYPES.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}{typeCounts[t] ? ` (${typeCounts[t]})` : ''}</option>)}
            </select>
          </Field>
          <Field label="Only in group" htmlFor="scope-group" help="Leave on every group to watch them all.">
            <select id="scope-group" value={scope.group || ''} disabled={disabled} onChange={(e) => set({ group: e.target.value })} className={cls()} data-testid="scope-group">
              <option value="">Every group</option>
              {groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </Field>
        </div>
      )}

      {scope.kind === 'tag' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Tag" error={errors['scope.tag']} htmlFor="scope-tag" testId="scope-tag-field"
            help={scope.tag ? `${matching} ${matching === 1 ? 'asset has' : 'assets have'} this tag now.` : tags.length ? 'Tags are set on the Assets page.' : undefined}>
            {tags.length ? (
              <select id="scope-tag" value={scope.tag || ''} disabled={disabled} onChange={(e) => set({ tag: e.target.value })} className={cls(errors['scope.tag'])} data-testid="scope-tag">
                <option value="">Pick a tag</option>
                {tags.map((t) => <option key={t.tag} value={t.tag}>{t.tag} ({t.count})</option>)}
              </select>
            ) : (
              <input id="scope-tag" value={scope.tag || ''} disabled={disabled} onChange={(e) => set({ tag: e.target.value })} placeholder="north pit" className={cls(errors['scope.tag'])} data-testid="scope-tag" />
            )}
          </Field>
          <Field label="Only in group" htmlFor="scope-group" help="Leave on every group to watch them all.">
            <select id="scope-group" value={scope.group || ''} disabled={disabled} onChange={(e) => set({ group: e.target.value })} className={cls()} data-testid="scope-group">
              <option value="">Every group</option>
              {groups.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </Field>
          {!tags.length && (
            <p className="text-xs text-slate-400 sm:col-span-2">
              No asset has a tag yet. <Link href="/telemetry/assets" className="text-cyan-300 hover:underline">Tag assets</Link> so a rule can follow them.
            </p>
          )}
        </div>
      )}
      {(scope.kind === 'type' || scope.kind === 'tag') && (
        <p className="text-xs text-slate-500">Assets get their type and tags on the <Link href="/telemetry/assets" className="text-cyan-300 hover:underline">Assets page</Link>. A part takes them from its asset.</p>
      )}
    </div>
  );
}
