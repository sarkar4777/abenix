'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { Activity, ArrowRight, Boxes, Loader2, Lock, Plus, Trash2, X } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { StatusDot } from '@/components/telemetry/bits';
import { apiFetch, ApiError } from '@/lib/api-client';
import { ago } from '@/lib/telemetry/format';
import { toastSuccess } from '@/stores/toastStore';
import TagInput from './TagInput';
import {
  ASSET_TYPES, FIXED_FIELDS, FIXED_LABEL, LIMITS, TYPE_INFO, assetPath, draftFromRow, explainAssetError, fieldKeyFrom,
  isDirty, keyFieldsText, locationText, newFieldRow, placeServerErrors, rowKey, statusOf, toPayload, typeLabel, validateDraft,
  type AssetDraft, type AssetRow, type DraftErrors, type LocKind,
} from './lib';

export type EditorState =
  | { kind: 'loading'; keyText: string }
  | { kind: 'missing'; keyText: string; text: string }
  | { kind: 'ready'; asset: AssetRow };

export interface AssetEditorProps {
  state: EditorState;
  // null means the person can change it, otherwise why not
  readOnly: string | null;
  teams: Array<{ id: string; name: string }>;
  tagSuggestions: string[];
  nextKey: string | null;
  now: number;
  onClose: () => void;
  onSaved: (row: AssetRow, goNext: boolean) => void;
  onRemoved: (row: AssetRow) => void;
}

function titleOf(state: EditorState, readOnly: string | null): string {
  if (state.kind !== 'ready') return 'Asset';
  const a = state.asset;
  const what = a.device ? 'part' : 'asset';
  if (readOnly) return a.display_name || `Unnamed ${what}`;
  return a.registered ? `Change ${a.display_name || `this ${what}`}` : `Name this ${what}`;
}

export default function AssetEditor(p: AssetEditorProps) {
  const { state } = p;
  const [dirty, setDirty] = useState(false);
  const [askDiscard, setAskDiscard] = useState(false);
  const [busy, setBusy] = useState(false);
  const [askRemove, setAskRemove] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeErr, setRemoveErr] = useState<string | null>(null);
  const close = () => {
    if (busy || removing) return;
    if (dirty) { setAskDiscard(true); return; }
    p.onClose();
  };
  const formKey = state.kind === 'ready' ? rowKey(state.asset) : '';
  const target = state.kind === 'ready' ? state.asset : null;

  async function remove() {
    if (!target) return;
    setRemoving(true);
    setRemoveErr(null);
    try {
      await apiFetch(assetPath(target.group, target.node, target.device), { method: 'DELETE' });
      toastSuccess('Name and details removed', `${rowKey(target)} keeps streaming and shows as unregistered again.`);
      setAskRemove(false);
      p.onRemoved(target);
    } catch (e) {
      setAskRemove(false);
      setRemoveErr(explainAssetError(e, 'delete'));
    } finally {
      setRemoving(false);
    }
  }

  return (
    <>
      <ResponsiveModal open onClose={askDiscard || askRemove ? () => {} : close} title={titleOf(state, p.readOnly)} icon={<Boxes className="h-4 w-4" />} maxWidth="max-w-2xl">
        <div data-testid="asset-editor" data-mode={p.readOnly ? 'view' : 'edit'} data-key={state.kind === 'ready' ? formKey : state.keyText}>
          {state.kind === 'loading' && (
            <div className="space-y-3" aria-busy="true" data-testid="asset-editor-loading">
              <div className="h-5 w-48 animate-pulse rounded bg-slate-800/60" />
              {[0, 1, 2, 3].map((i) => <div key={i} className="h-10 animate-pulse rounded-md bg-slate-800/40" />)}
            </div>
          )}
          {state.kind === 'missing' && (
            <div className="space-y-3" data-testid="asset-editor-missing">
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-100" role="alert">{state.text}</p>
              <button type="button" onClick={p.onClose} className="min-h-[40px] rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800">Back to the list</button>
            </div>
          )}
          {state.kind === 'ready' && (
            p.readOnly
              ? <AssetDetail asset={state.asset} reason={p.readOnly} now={p.now} onClose={p.onClose} />
              : <EditorForm key={formKey} {...p} asset={state.asset} onDirty={setDirty} busy={busy || removing} setBusy={setBusy} onCancel={close} onAskRemove={() => { setRemoveErr(null); setAskRemove(true); }} removeErr={removeErr} />
          )}
        </div>
      </ResponsiveModal>
      <ConfirmModal
        open={askDiscard}
        onClose={() => setAskDiscard(false)}
        onConfirm={() => { setAskDiscard(false); p.onClose(); }}
        title="Discard your changes?"
        description="What you typed in this asset has not been saved. Closing now drops it."
        confirmLabel="Discard"
        cancelLabel="Keep editing"
        variant="warning"
        confirmTestId="asset-discard-confirm"
      />
      {target && (
        <ConfirmModal
          open={askRemove}
          onClose={() => { if (!removing) setAskRemove(false); }}
          onConfirm={() => void remove()}
          loading={removing}
          title="Remove the name and details?"
          description={`Abenix forgets the name, type, tags, team, location and fields of ${rowKey(target)}. The stream keeps flowing and the ${target.device ? 'part' : 'asset'} shows as unregistered until someone names it again.`}
          confirmLabel="Remove"
          confirmTestId="asset-remove-confirm"
        />
      )}
    </>
  );
}

function Header({ asset, now }: { asset: AssetRow; now: number }) {
  const st = statusOf(asset);
  const liveHref = `/telemetry?group=${encodeURIComponent(asset.group)}&node=${encodeURIComponent(asset.node)}${asset.device ? `&device=${encodeURIComponent(asset.device)}` : ''}`;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-xs text-slate-300">
      <span className="min-w-0 break-all font-mono text-slate-100" data-testid="asset-key">{rowKey(asset)}</span>
      <span className="inline-flex items-center gap-1.5"><StatusDot status={st.tone} />{st.label}{asset.last_seen ? `, ${ago(asset.last_seen, now)}` : ''}</span>
      {asset.device ? <span className="text-slate-400">Part of {asset.node}</span> : asset.parts?.length ? <span className="text-slate-400">{asset.parts.length} part{asset.parts.length === 1 ? '' : 's'}</span> : null}
      {asset.live && (
        <Link href={liveHref} className="ml-auto inline-flex items-center gap-1 text-cyan-300 hover:underline" data-testid="asset-open-live">
          <Activity className="h-3.5 w-3.5" /> Live data <ArrowRight className="h-3 w-3" />
        </Link>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-0.5 border-b border-slate-800 py-2 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-sm text-slate-100">{children}</dd>
    </div>
  );
}

const none = <span className="text-slate-500">Not set</span>;

function AssetDetail({ asset, reason, now, onClose }: { asset: AssetRow; reason: string; now: number; onClose: () => void }) {
  const extra = Object.entries(asset.fields || {}).filter(([k]) => !(FIXED_FIELDS as readonly string[]).includes(k));
  return (
    <div data-testid="asset-detail">
      <Header asset={asset} now={now} />
      <p className="mb-3 flex items-start gap-2 rounded-lg border border-slate-600/60 bg-slate-800/40 px-3 py-2 text-xs text-slate-300" data-testid="asset-read-only-why">
        <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" /> {reason}
      </p>
      {!asset.registered && <p className="mb-3 text-sm text-slate-300">Nobody has named this {asset.device ? 'part' : 'asset'} yet, so it is known only by its key.</p>}
      <dl>
        <Row label="Name">{asset.display_name || none}</Row>
        <Row label="Type">{asset.type ? `${typeLabel(asset.type)}` : none}</Row>
        <Row label="Tags">
          {asset.tags?.length ? <span className="flex flex-wrap gap-1">{asset.tags.map((t) => <span key={t} className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-200">{t}</span>)}</span> : none}
        </Row>
        <Row label="Team">{asset.team_name || 'Whole workspace'}</Row>
        <Row label="Location">{locationText(asset.location) || none}</Row>
        <Row label="Key details">{keyFieldsText(asset.fields) || none}</Row>
        {extra.length > 0 && (
          <Row label="Other fields">
            <span className="block space-y-0.5">{extra.map(([k, v]) => <span key={k} className="block"><span className="font-mono text-xs text-slate-400">{k}</span> {v}</span>)}</span>
          </Row>
        )}
        {asset.updated_at && <Row label="Last changed">{new Date(asset.updated_at).toLocaleString()}</Row>}
      </dl>
      <div className="mt-4 flex justify-end">
        <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" data-testid="asset-detail-close">Close</button>
      </div>
    </div>
  );
}

function Err({ id, text }: { id: string; text?: string }) {
  if (!text) return null;
  return <p id={id} className="mt-1 text-xs text-rose-300" role="alert" data-testid={`asset-err-${id.replace(/^asset-err-/, '')}`}>{text}</p>;
}

const input = (bad: boolean) => `w-full rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white placeholder:text-slate-600 ${bad ? 'border-rose-500/60' : 'border-slate-700'}`;

function EditorForm({
  asset, teams, tagSuggestions, nextKey, now, onSaved, onDirty, busy, setBusy, onCancel, onAskRemove, removeErr,
}: AssetEditorProps & {
  asset: AssetRow;
  onDirty: (dirty: boolean) => void;
  onAskRemove: () => void;
  removeErr: string | null;
  busy: boolean;
  setBusy: (b: boolean) => void;
  onCancel: () => void;
}) {
  const [original] = useState(() => draftFromRow(asset));
  const [draft, setDraft] = useState<AssetDraft>(() => draftFromRow(asset));
  const [server, setServer] = useState<DraftErrors>({});
  const [formErr, setFormErr] = useState<string | null>(null);

  const client = useMemo(() => validateDraft(draft), [draft]);
  const errs: DraftErrors = { ...server, ...client };
  const dirty = isDirty(draft, original);
  const valid = Object.keys(client).length === 0;
  useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);

  const edit = (patch: Partial<AssetDraft>, keys: string[]) => {
    setDraft((d) => ({ ...d, ...patch }));
    if (keys.some((k) => server[k]) || server.form) {
      setServer((s) => { const n = { ...s }; for (const k of keys) delete n[k]; delete n.form; return n; });
    }
    setFormErr(null);
  };

  const teamOptions = useMemo(() => {
    const list = [...teams];
    if (asset.team_id && !list.some((t) => t.id === asset.team_id)) list.unshift({ id: asset.team_id, name: asset.team_name || 'Its current team' });
    return list;
  }, [teams, asset.team_id, asset.team_name]);

  async function save(goNext: boolean) {
    if (!dirty || !valid || busy) return;
    setBusy(true);
    setFormErr(null);
    setServer({});
    try {
      const res = await apiFetch<AssetRow>(assetPath(asset.group, asset.node, asset.device), { method: 'PUT', body: JSON.stringify(toPayload(draft)) });
      const row = res.data ?? { ...asset, ...toPayload(draft), registered: true } as AssetRow;
      const name = row.display_name || draft.display_name.trim() || rowKey(asset);
      toastSuccess(`${name} saved`, 'Rules, filters and agents can use its name, type and tags now.');
      onSaved(row, goNext);
    } catch (e) {
      const fields = e instanceof ApiError ? (e.details?.fields as unknown) : undefined;
      const placed = placeServerErrors(fields, draft);
      setServer(placed);
      const general = placed.form;
      setFormErr(general || explainAssetError(e, 'save'));
    } finally {
      setBusy(false);
    }
  }

  const saveTitle = !dirty ? 'Nothing has changed yet' : !valid ? 'Fix the fields marked in red first' : undefined;
  const errCount = Object.keys(client).length;

  return (
    <form onSubmit={(e) => { e.preventDefault(); void save(false); }} className="space-y-5" noValidate>
      <Header asset={asset} now={now} />

      <div>
        <label htmlFor="asset-name" className="mb-1 block text-xs font-medium text-slate-300">Name</label>
        <input
          id="asset-name"
          value={draft.display_name}
          onChange={(e) => edit({ display_name: e.target.value }, ['display_name'])}
          placeholder={asset.device ? 'Engine ECU' : 'Truck 42, Press line 3'}
          maxLength={LIMITS.name + 40}
          aria-invalid={!!errs.display_name}
          aria-describedby={errs.display_name ? 'asset-err-display_name' : 'asset-name-help'}
          className={input(!!errs.display_name)}
          data-testid="asset-name"
          autoFocus
        />
        {errs.display_name ? <Err id="asset-err-display_name" text={errs.display_name} /> : <p id="asset-name-help" className="mt-1 text-xs text-slate-500">What people call it. Shown everywhere instead of {rowKey(asset)}.</p>}
      </div>

      <fieldset>
        <legend className="mb-1 text-xs font-medium text-slate-300">Type</legend>
        <div className="grid gap-1.5 sm:grid-cols-2" role="radiogroup" aria-label="Type">
          {(['', ...ASSET_TYPES] as const).map((t) => {
            const on = draft.type === t;
            return (
              <button
                key={t || 'none'}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => edit({ type: t }, ['type'])}
                className={`min-w-0 rounded-lg border px-3 py-2 text-left ${on ? 'border-cyan-400 bg-cyan-500/10' : 'border-slate-700 hover:border-slate-500'}`}
                data-testid={`asset-type-${t || 'none'}`}
              >
                <span className="block text-sm font-medium text-white">{t ? TYPE_INFO[t].label : 'Not set'}</span>
                <span className="block truncate text-[11px] text-slate-400">{t ? TYPE_INFO[t].hint : 'Leave it open for now'}</span>
              </button>
            );
          })}
        </div>
        <Err id="asset-err-type" text={errs.type} />
      </fieldset>

      <div>
        <label htmlFor="asset-tags" className="mb-1 block text-xs font-medium text-slate-300">Tags</label>
        <TagInput id="asset-tags" tags={draft.tags} onChange={(tags) => edit({ tags }, ['tags'])} suggestions={tagSuggestions} problem={errs.tags} describedBy="asset-tags-help" />
        <p id="asset-tags-help" className="mt-1 text-xs text-slate-500">Press Enter or type a comma to add one. Up to {LIMITS.tags}, stored in lower case.</p>
      </div>

      <div>
        <label htmlFor="asset-team" className="mb-1 block text-xs font-medium text-slate-300">Team</label>
        <select id="asset-team" value={draft.team_id} onChange={(e) => edit({ team_id: e.target.value }, ['team_id'])} className={input(!!errs.team_id)} data-testid="asset-team">
          <option value="">Whole workspace</option>
          {teamOptions.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        {errs.team_id ? <Err id="asset-err-team_id" text={errs.team_id} /> : <p className="mt-1 text-xs text-slate-500">{draft.team_id ? 'This team owns the asset. Rules and filters can pick it by team.' : 'No single team owns it.'}{!teams.length ? ' Teams are made under Admin, Permissions.' : ''}</p>}
      </div>

      <fieldset>
        <legend className="mb-1 text-xs font-medium text-slate-300">Location</legend>
        <div className="inline-flex flex-wrap rounded-lg border border-slate-700 p-0.5" role="radiogroup" aria-label="Location">
          {([['none', 'Not set'], ['gps', 'GPS'], ['site', 'Site map']] as Array<[LocKind, string]>).map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={draft.loc === k} onClick={() => edit({ loc: k }, ['location', 'lat', 'lon', 'x', 'y'])} className={`min-h-[34px] rounded-md px-3 py-1 text-xs ${draft.loc === k ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid={`asset-loc-${k}`}>
              {label}
            </button>
          ))}
        </div>
        {draft.loc !== 'none' && (
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {(draft.loc === 'gps'
              ? [['lat', 'Latitude', '52.3702', '-90 to 90'], ['lon', 'Longitude', '4.8952', '-180 to 180']]
              : [['x', 'X on the site map', '120', 'Metres or your own units'], ['y', 'Y on the site map', '45', 'Metres or your own units']]
            ).map(([k, label, ph, hint]) => (
              <div key={k}>
                <label htmlFor={`asset-${k}`} className="mb-1 block text-[11px] text-slate-400">{label}</label>
                <input
                  id={`asset-${k}`}
                  inputMode="decimal"
                  value={draft[k as 'lat' | 'lon' | 'x' | 'y']}
                  onChange={(e) => edit({ [k]: e.target.value } as Partial<AssetDraft>, [k, 'location'])}
                  placeholder={ph}
                  aria-invalid={!!errs[k]}
                  className={input(!!errs[k])}
                  data-testid={`asset-${k}`}
                />
                {errs[k] ? <Err id={`asset-err-${k}`} text={errs[k]} /> : <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
              </div>
            ))}
            <div className="sm:col-span-2">
              <label htmlFor="asset-loc-label" className="mb-1 block text-[11px] text-slate-400">Place name, optional</label>
              <input id="asset-loc-label" value={draft.label} onChange={(e) => edit({ label: e.target.value }, ['location'])} placeholder={draft.loc === 'gps' ? 'North depot' : 'Hall B, bay 4'} className={input(false)} data-testid="asset-loc-label" />
            </div>
          </div>
        )}
        <Err id="asset-err-location" text={errs.location} />
      </fieldset>

      <fieldset>
        <legend className="mb-1 text-xs font-medium text-slate-300">Details</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {FIXED_FIELDS.map((k) => (
            <div key={k}>
              <label htmlFor={`asset-field-${k}`} className="mb-1 block text-[11px] text-slate-400">{FIXED_LABEL[k]}</label>
              <input id={`asset-field-${k}`} value={draft.fixed[k]} onChange={(e) => edit({ fixed: { ...draft.fixed, [k]: e.target.value } }, [k, 'fields'])} aria-invalid={!!errs[k]} className={input(!!errs[k])} data-testid={`asset-field-${k}`} />
              <Err id={`asset-err-${k}`} text={errs[k]} />
            </div>
          ))}
        </div>
        {draft.custom.length > 0 && (
          <ul className="mt-3 space-y-2" aria-label="Other fields">
            {draft.custom.map((r, i) => {
              const ke = errs[`custom.${r.id}.key`];
              const ve = errs[`custom.${r.id}.value`];
              const setRow = (patch: Partial<typeof r>) => edit({ custom: draft.custom.map((x) => (x.id === r.id ? { ...x, ...patch } : x)) }, [`custom.${r.id}.key`, `custom.${r.id}.value`, 'fields']);
              return (
                <li key={r.id} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] items-start gap-2" data-testid="asset-custom-row">
                  <div className="min-w-0">
                    <label htmlFor={`asset-ck-${r.id}`} className="sr-only">Field name {i + 1}</label>
                    <input id={`asset-ck-${r.id}`} value={r.key} onChange={(e) => setRow({ key: fieldKeyFrom(e.target.value) })} placeholder="fleet_no" aria-invalid={!!ke} className={`${input(!!ke)} font-mono`} data-testid="asset-custom-key" />
                    <Err id={`asset-err-ck-${r.id}`} text={ke} />
                  </div>
                  <div className="min-w-0">
                    <label htmlFor={`asset-cv-${r.id}`} className="sr-only">Value {i + 1}</label>
                    <input id={`asset-cv-${r.id}`} value={r.value} onChange={(e) => setRow({ value: e.target.value })} placeholder="Value" aria-invalid={!!ve} className={input(!!ve)} data-testid="asset-custom-value" />
                    <Err id={`asset-err-cv-${r.id}`} text={ve} />
                  </div>
                  <button type="button" onClick={() => edit({ custom: draft.custom.filter((x) => x.id !== r.id) }, ['fields'])} aria-label={`Remove field ${r.key || i + 1}`} className="mt-1 rounded-md p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white">
                    <X className="h-4 w-4" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        <button type="button" onClick={() => edit({ custom: [...draft.custom, newFieldRow()] }, [])} className="mt-2 inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800" data-testid="asset-add-field">
          <Plus className="h-3.5 w-3.5" /> Add field
        </button>
        <Err id="asset-err-fields" text={errs.fields} />
      </fieldset>

      {(formErr || removeErr) && <p className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-100" role="alert" data-testid="asset-editor-error">{formErr || removeErr}</p>}
      {errCount > 0 && dirty && <p className="text-xs text-rose-300">{errCount === 1 ? 'One field needs' : `${errCount} fields need`} fixing before you can save.</p>}

      <div className="flex flex-col-reverse gap-2 border-t border-slate-800 pt-3 sm:flex-row sm:items-center">
        {asset.registered && (
          <button type="button" onClick={onAskRemove} disabled={busy} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm text-rose-300 hover:bg-rose-500/10 disabled:opacity-50" data-testid="asset-remove">
            <Trash2 className="h-4 w-4" /> Remove name and details
          </button>
        )}
        <span className="flex-1" />
        <button type="button" onClick={onCancel} disabled={busy} className="min-h-[40px] rounded-lg px-3 py-2 text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
        {nextKey && (
          <button type="button" onClick={() => void save(true)} disabled={!dirty || !valid || busy} title={saveTitle} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg border border-cyan-500/50 px-4 py-2 text-sm text-cyan-100 hover:bg-cyan-500/10 disabled:cursor-not-allowed disabled:opacity-50" data-testid="asset-save-next">
            Save and name the next <ArrowRight className="h-4 w-4" />
          </button>
        )}
        <button type="submit" disabled={!dirty || !valid || busy} title={saveTitle} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50" data-testid="asset-save">
          {busy && <Loader2 className="h-4 w-4 animate-spin" />} Save
        </button>
      </div>

    </form>
  );
}
