'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import useSWR from 'swr';
import { AlertTriangle, Boxes, Plug, RefreshCw, Search, Tag, Upload, X } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NoAccess from '@/components/layout/NoAccess';
import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { holds, useMyPermissions } from '@/lib/capabilities';
import AssetEditor, { type EditorState } from '@/components/telemetry-rules/assets/AssetEditor';
import { AssetCards, AssetTable, ListSkeleton, Pager } from '@/components/telemetry-rules/assets/AssetList';
import ImportDialog from '@/components/telemetry-rules/assets/ImportDialog';
import {
  assetPath, explainAssetError, facetsOf, filterFromParams, isFiltered, listUrl, matchAsset, nextUnregistered, pageSlice,
  parseAssetKey, plural, replaceRow, rowKey, sortAssets, typeLabel, type AssetFilter, type AssetRow, type AssetsMeta,
} from '@/components/telemetry-rules/assets/lib';

const PURPOSE = 'Name the vehicles, machines, sensors and systems that stream in, so rules, filters and agents can use their names, types and tags.';
const WHO_CAN = 'An admin, or anyone with Manage telemetry, can name assets and import them.';
const PAGE = 100;

type Envelope = Awaited<ReturnType<typeof apiFetch<unknown>>>;

function fetcher(url: string) {
  return apiFetch<unknown>(url, { silent: true });
}

function envErr(res: Envelope | undefined, swrErr: unknown): string | null {
  if (res?.error) return explainAssetError({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }, 'load');
  if (swrErr) return explainAssetError(swrErr, 'load');
  return null;
}

function rowsOf(res: Envelope | undefined): AssetRow[] | null {
  const d = res?.data;
  if (Array.isArray(d)) return d as AssetRow[];
  if (d && typeof d === 'object' && Array.isArray((d as { assets?: unknown }).assets)) return (d as { assets: AssetRow[] }).assets;
  return null;
}

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(h);
  }, [ms]);
  return now;
}

function AssetsPage() {
  usePageTitle('Assets');
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { perms, loading: permsLoading } = useMyPermissions();
  const caps = perms?.capabilities;
  const canView = holds(caps, 'telemetry.view');
  const canManage = holds(caps, 'telemetry.manage');
  const now = useNow(15_000);

  const filter: AssetFilter = useMemo(() => filterFromParams((k) => params.get(k)), [params]);
  const editParam = params.get('edit');
  const editKey = useMemo(() => parseAssetKey(editParam), [editParam]);

  const setParams = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(Array.from(params.entries()));
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k);
      else next.set(k, v);
    }
    const qs = next.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ''}`, { scroll: false });
  }, [params, pathname, router]);

  const base = useSWR(canView ? listUrl(filter) : null, fetcher, { refreshInterval: 60_000, revalidateOnFocus: false, keepPreviousData: true });
  const baseRows = rowsOf(base.data);
  const meta = (base.data?.meta ?? null) as AssetsMeta | null;
  // past the 5000 the page holds, filters run on the server
  const truncated = !!baseRows && typeof meta?.total === 'number' && meta.total > baseRows.length;
  const serverFiltered = useSWR(canView && truncated && isFiltered(filter) ? listUrl(filter, true) : null, fetcher, { revalidateOnFocus: false, keepPreviousData: true });
  const teamsRes = useSWR(canManage ? '/api/telemetry/teams' : null, fetcher, { revalidateOnFocus: false });
  const teams = Array.isArray(teamsRes.data?.data) ? (teamsRes.data!.data as Array<{ id: string; name: string }>) : [];

  const sourceRows = (truncated && isFiltered(filter) ? rowsOf(serverFiltered.data) : null) ?? baseRows;
  const all = useMemo(() => sortAssets(baseRows ?? []), [baseRows]);
  const list = useMemo(() => sortAssets((sourceRows ?? []).filter((r) => matchAsset(r, filter))), [sourceRows, filter]);
  const facets = useMemo(() => facetsOf(baseRows ?? []), [baseRows]);
  const typeOptions = useMemo(() => {
    const v = facets.types.map((t) => t.value);
    if (filter.type && !v.includes(filter.type)) v.push(filter.type);
    return v;
  }, [facets.types, filter.type]);
  const tagOptions = useMemo(() => {
    const fromMeta = (meta?.tags ?? []).map((t) => t.tag);
    const v = Array.from(new Set([...facets.tags.map((t) => t.value), ...fromMeta])).sort();
    if (filter.tag && !v.includes(filter.tag)) v.push(filter.tag);
    return v;
  }, [facets.tags, meta?.tags, filter.tag]);
  const unregistered = typeof meta?.unregistered === 'number' ? meta.unregistered : all.filter((r) => !r.registered && (filter.parts || !r.device)).length;

  const error = envErr(base.data, base.error);
  const loading = !baseRows && !error;

  const [q, setQ] = useState(filter.q);
  useEffect(() => setQ(filter.q), [filter.q]);
  useEffect(() => {
    if (q === filter.q) return;
    const t = setTimeout(() => setParams({ q: q || null }), 250);
    return () => clearTimeout(t);
  }, [q, filter.q, setParams]);

  const [page, setPage] = useState(0);
  const filterSig = `${filter.q}|${filter.type}|${filter.tag}|${filter.status}|${filter.parts}`;
  useEffect(() => setPage(0), [filterSig]);
  const slice = pageSlice(list.length, page, PAGE);
  const pageRows = useMemo(() => list.slice(slice.from, slice.to), [list, slice.from, slice.to]);

  const [importOpen, setImportOpen] = useState(false);

  // the asset in the editor, from the list or fetched on its own for a deep link
  const listed = useMemo(() => {
    if (!editKey) return null;
    const pool = [...(sourceRows ?? []), ...(baseRows ?? [])];
    return pool.find((r) => r.group === editKey.group && r.node === editKey.node && (r.device || '') === editKey.device) ?? null;
  }, [editKey, sourceRows, baseRows]);
  const single = useSWR(canView && editKey && !listed && baseRows ? assetPath(editKey.group, editKey.node, editKey.device) : null, fetcher, { revalidateOnFocus: false });
  const editorState: EditorState | null = useMemo(() => {
    if (!editParam) return null;
    if (!editKey) return { kind: 'missing', keyText: editParam, text: `"${editParam}" is not an asset key. Keys look like group/asset/part, with the part left empty for the asset itself.` };
    const keyText = `${editKey.group}/${editKey.node}/${editKey.device}`;
    if (listed) return { kind: 'ready', asset: listed };
    const d = single.data;
    if (d?.data && typeof d.data === 'object') return { kind: 'ready', asset: d.data as AssetRow };
    if (d?.errorDetail?.code === 404) return { kind: 'missing', keyText, text: `Abenix has no asset with the key ${keyText}. It shows up once its source sends data, or after it is imported from a CSV.` };
    if (d?.error) return { kind: 'missing', keyText, text: explainAssetError({ status: d.errorDetail?.code, code: d.errorDetail?.error_code, message: d.error }, 'load') };
    if (error) return { kind: 'missing', keyText, text: error };
    return { kind: 'loading', keyText };
  }, [editParam, editKey, listed, single.data, error]);

  const editing = editorState?.kind === 'ready' ? editorState.asset : null;
  const readOnly = !canManage
    ? `You can look but not change it. ${WHO_CAN}`
    : editing && !editing.can_edit
      ? 'You can see this asset but not change it, because it belongs to a team you are not part of. An admin can change it.'
      : null;
  const nextKey = useMemo(() => {
    if (!editing || editing.registered || readOnly) return null;
    return nextUnregistered(list.length ? list : all, rowKey(editing));
  }, [editing, readOnly, list, all]);

  const open = useCallback((r: AssetRow) => setParams({ edit: rowKey(r) }), [setParams]);
  const canEditRow = useCallback((r: AssetRow) => canManage && r.can_edit !== false, [canManage]);

  const patchRow = useCallback((row: AssetRow) => {
    const swap = (res: Envelope | undefined) => {
      const rows = rowsOf(res);
      return res && rows ? { ...res, data: replaceRow(rows, row) } : res;
    };
    void base.mutate(swap, { revalidate: true });
    if (serverFiltered.data) void serverFiltered.mutate(swap, { revalidate: true });
    if (single.data) void single.mutate();
  }, [base, serverFiltered, single]);

  const onSaved = useCallback((row: AssetRow, goNext: boolean) => {
    patchRow(row);
    setParams({ edit: goNext && nextKey ? nextKey : null });
  }, [patchRow, setParams, nextKey]);
  const onRemoved = useCallback(() => {
    void base.mutate();
    if (serverFiltered.data) void serverFiltered.mutate();
    setParams({ edit: null });
  }, [base, serverFiltered, setParams]);

  const nameThem = () => {
    const first = all.find((r) => !r.registered && (filter.parts || !r.device));
    setParams({ status: 'unregistered', edit: first ? rowKey(first) : null });
  };
  const clearFilters = () => { setQ(''); setParams({ q: null, type: null, tag: null, status: null }); };

  if (permsLoading && !perms) {
    return <div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>;
  }
  if (perms && !canView) {
    return (
      <NoAccess
        testId="assets-no-access"
        title="Assets"
        purpose={PURPOSE}
        icon={Boxes}
        need={{ capability: 'telemetry.view', label: 'View machine telemetry' }}
        role={perms.role}
        instead={{ text: 'Alerts lists anything that went wrong, including assets that went offline.', href: '/alerts', label: 'Open Alerts' }}
      />
    );
  }

  const filtered = isFiltered(filter);
  const sel = 'min-h-[40px] rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200';

  return (
    <div className="mx-auto max-w-7xl space-y-4" data-testid="assets-page">
      <PageHeader
        title="Assets"
        purpose={PURPOSE}
        icon={Boxes}
        storageKey="telemetry-assets"
        back={{ href: '/telemetry', label: 'Telemetry' }}
        primaryAction={canManage ? { label: 'Import CSV', icon: Upload, onClick: () => setImportOpen(true), testId: 'assets-import' } : undefined}
        extraActions={
          <button type="button" onClick={() => void base.mutate()} disabled={base.isValidating} className="hidden min-h-[40px] items-center justify-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-60 sm:inline-flex" aria-label="Refresh the list" title="Refresh the list" data-testid="assets-refresh">
            <RefreshCw className={`h-4 w-4 ${base.isValidating ? 'animate-spin' : ''}`} />
          </button>
        }
        steps={[
          { title: 'Streams arrive', body: 'Every asset and part that sends data shows up here by itself, at first under its raw key and marked Unregistered.' },
          { title: 'Name it', body: 'Give it a name people know, a type, tags and a team. Add where it is and details such as VIN, plate or serial number.' },
          { title: 'Or import a list', body: 'Upload a CSV to name hundreds at once. Abenix checks every row and shows what would change before anything is saved.' },
          { title: 'Use it everywhere', body: 'Rules, filters and agents pick assets by name, type, tag and team instead of raw keys.' },
        ]}
        howItWorks={
          <p className="text-xs text-slate-400">
            Keys follow Group, Asset and Part. Removing a name only forgets the details. The stream keeps flowing and the asset shows as unregistered again.
          </p>
        }
      />

      {perms && !canManage && (
        <ViewOnlyBanner testId="assets-view-only">
          You can see the assets shared with you or your team. {WHO_CAN}
        </ViewOnlyBanner>
      )}

      {!loading && !error && unregistered > 0 && filter.status !== 'unregistered' && (
        <div className="flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-100 sm:flex-row sm:items-center" role="status" data-testid="assets-unregistered-banner">
          <Tag className="hidden h-4 w-4 shrink-0 text-amber-300 sm:block" aria-hidden />
          <p className="min-w-0 flex-1">
            <span className="font-medium text-white">{plural(unregistered, 'asset is', 'assets are')} streaming without a name.</span>{' '}
            {canManage ? 'Name them so people, rules and agents know what they are.' : 'Someone with Manage telemetry can name them.'}
          </p>
          {canManage && (
            <button type="button" onClick={nameThem} className="inline-flex min-h-[40px] shrink-0 items-center justify-center rounded-lg bg-amber-500 px-4 py-2 text-sm font-medium text-slate-950 hover:bg-amber-400" data-testid="assets-name-them">
              Name them
            </button>
          )}
        </div>
      )}

      {error && baseRows ? (
        <p className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-sm text-amber-100" role="alert" data-testid="assets-stale">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> The list could not refresh, so it may be out of date. {error}
        </p>
      ) : null}

      {error && !baseRows ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-100" role="alert" data-testid="assets-error">
          <p>{error}</p>
          <button type="button" onClick={() => void base.mutate()} className="mt-2 inline-flex min-h-[36px] items-center gap-1.5 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800" data-testid="assets-retry">
            <RefreshCw className="h-3.5 w-3.5" /> Try again
          </button>
        </div>
      ) : loading ? (
        <ListSkeleton />
      ) : all.length === 0 && !filtered ? (
        <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center sm:p-10" data-testid="assets-empty">
          <Boxes className="mx-auto h-8 w-8 text-cyan-400" />
          <h2 className="mt-3 text-base font-semibold text-white">No assets yet</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm text-slate-300">
            Assets appear when a source sends data, or import a list of the ones you have.
          </p>
          <div className="mt-4 flex flex-col justify-center gap-2 sm:flex-row">
            <Link href="/telemetry?tab=sources" className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-200 hover:bg-slate-800" data-testid="assets-empty-sources">
              <Plug className="h-4 w-4" /> {canManage ? 'Add or check a source' : 'See the sources'}
            </Link>
            {canManage && (
              <button type="button" onClick={() => setImportOpen(true)} className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400" data-testid="assets-empty-import">
                <Upload className="h-4 w-4" /> Import CSV
              </button>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2" data-testid="assets-filters">
            <label className="relative min-w-0 flex-[1_1_14rem] sm:max-w-xs">
              <span className="sr-only">Search assets</span>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Name, key, tag, VIN"
                className="min-h-[40px] w-full rounded-lg border border-slate-700 bg-slate-900 py-2 pl-8 pr-8 text-sm text-white placeholder:text-slate-500"
                data-testid="assets-search"
              />
              {q && (
                <button type="button" onClick={() => { setQ(''); setParams({ q: null }); }} aria-label="Clear search" className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-slate-400 hover:text-white">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </label>
            <select value={filter.status} onChange={(e) => setParams({ status: e.target.value || null })} aria-label="Named or not" className={`${sel} min-w-0 flex-1 sm:flex-none`} data-testid="assets-filter-status">
              <option value="">Named and unnamed</option>
              <option value="registered">Named</option>
              <option value="unregistered">Unregistered</option>
            </select>
            <select value={filter.type} onChange={(e) => setParams({ type: e.target.value || null })} aria-label="Type" disabled={!typeOptions.length} title={!typeOptions.length ? 'No asset has a type yet' : undefined} className={`${sel} min-w-0 flex-1 disabled:opacity-50 sm:flex-none`} data-testid="assets-filter-type">
              <option value="">All types</option>
              {typeOptions.map((t) => <option key={t} value={t}>{typeLabel(t)}</option>)}
            </select>
            <select value={filter.tag} onChange={(e) => setParams({ tag: e.target.value || null })} aria-label="Tag" disabled={!tagOptions.length} title={!tagOptions.length ? 'No asset has a tag yet' : undefined} className={`${sel} min-w-0 flex-1 disabled:opacity-50 sm:flex-none`} data-testid="assets-filter-tag">
              <option value="">All tags</option>
              {tagOptions.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <label className="inline-flex min-h-[40px] items-center gap-2 rounded-lg border border-slate-700 px-3 text-sm text-slate-200">
              <input type="checkbox" checked={filter.parts} onChange={(e) => setParams({ parts: e.target.checked ? '1' : null })} className="accent-cyan-500" data-testid="assets-show-parts" />
              Show parts
            </label>
            <span className="ml-auto text-xs text-slate-400" data-testid="assets-count" aria-live="polite">
              {filtered ? `${list.length.toLocaleString('en-US')} of ${all.length.toLocaleString('en-US')}` : plural(all.length, filter.parts ? 'asset or part' : 'asset', filter.parts ? 'assets and parts' : 'assets')}
              {truncated ? `, ${all.length.toLocaleString('en-US')} of ${(meta?.total ?? 0).toLocaleString('en-US')} loaded, search to narrow` : ''}
            </span>
          </div>

          {list.length === 0 ? (
            <div className="rounded-xl border border-slate-700/60 bg-slate-900/40 p-6 text-center text-sm text-slate-300" data-testid="assets-no-match">
              <p>{serverFiltered.isLoading ? 'Searching all assets' : 'No assets match these filters.'}</p>
              {!serverFiltered.isLoading && (
                <button type="button" onClick={clearFilters} className="mt-2 inline-flex min-h-[36px] items-center text-cyan-300 hover:underline" data-testid="assets-clear-filters">Clear filters</button>
              )}
            </div>
          ) : (
            <>
              <AssetTable rows={pageRows} now={now} onOpen={open} canEdit={canEditRow} />
              <AssetCards rows={pageRows} now={now} onOpen={open} canEdit={canEditRow} />
              <Pager from={slice.from} to={slice.to} total={list.length} page={slice.page} pages={slice.pages} setPage={(n) => { setPage(n); window.scrollTo({ top: 0, behavior: 'smooth' }); }} />
            </>
          )}
        </div>
      )}

      {editorState && (
        <AssetEditor
          state={editorState}
          readOnly={readOnly}
          teams={teams}
          tagSuggestions={tagOptions}
          nextKey={nextKey}
          now={now}
          onClose={() => setParams({ edit: null })}
          onSaved={onSaved}
          onRemoved={onRemoved}
        />
      )}
      {importOpen && canManage && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImported={() => { void base.mutate(); if (serverFiltered.data) void serverFiltered.mutate(); }}
        />
      )}
    </div>
  );
}

export default function AssetsRoute() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-7xl"><div className="h-40 animate-pulse rounded-xl bg-slate-800/40" /></div>}>
      <AssetsPage />
    </Suspense>
  );
}
