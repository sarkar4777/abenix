'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowRight, Ban, Loader2, Pencil, RefreshCw, TerminalSquare, Trash2, X } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import { toastError, toastSuccess } from '@/stores/toastStore';
import { StatusChip } from './GatewayCard';
import InstallPanel from './InstallPanel';
import {
  COLLECTOR_STATUS, bytes, count, duration, edgeCall, telemetryHref, timeAgo,
  type Gateway, type InstallOut,
} from './model';

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex min-w-0 justify-between gap-3 border-b border-slate-800/70 py-1.5 text-xs">
      <span className="shrink-0 text-slate-400">{k}</span>
      <span className="min-w-0 break-words text-right text-slate-100">{v}</span>
    </div>
  );
}

export default function GatewayDetail({ id, onClose, onEdit, onChanged, canManage }: {
  id: string;
  onClose: () => void;
  onEdit: (g: Gateway) => void;
  onChanged: () => void;
  canManage: boolean;
}) {
  const [g, setG] = useState<Gateway | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [install, setInstall] = useState<InstallOut | null>(null);
  const [showInstall, setShowInstall] = useState(false);
  const [confirm, setConfirm] = useState<null | 'revoke' | 'remove'>(null);
  const [removeSource, setRemoveSource] = useState(false);
  const [busy, setBusy] = useState(false);
  useEscapeToClose(!confirm, onClose);

  const load = useCallback(async () => {
    const r = await edgeCall<Gateway>(`/api/edge/gateways/${id}`);
    if (r.error) setErr(r.error);
    else { setErr(null); setG(r.data); }
  }, [id]);

  useEffect(() => {
    load();
    const h = setInterval(load, 5000);
    return () => clearInterval(h);
  }, [load]);

  const revoke = async () => {
    setBusy(true);
    const r = await edgeCall<Gateway>(`/api/edge/gateways/${id}/revoke`, 'POST');
    setBusy(false);
    setConfirm(null);
    if (r.error) { toastError('Could not revoke the gateway', r.error); return; }
    toastSuccess('Gateway revoked', 'Abenix now refuses its key. Readings stay in its buffer until it is enrolled again.');
    setG(r.data);
    onChanged();
  };

  const remove = async () => {
    setBusy(true);
    const r = await edgeCall<{ deleted: boolean }>(`/api/edge/gateways/${id}${removeSource ? '?remove_source=true' : ''}`, 'DELETE');
    setBusy(false);
    setConfirm(null);
    if (r.error) { toastError('Could not remove the gateway', r.error); return; }
    toastSuccess('Gateway removed', removeSource ? 'Its source and key are gone too.' : 'Its readings stay in Telemetry.');
    onChanged();
    onClose();
  };

  const b = g?.buffer || {};
  const u = g?.uplink || {};
  const fillPct = b.max_bytes ? Math.min(100, Math.round((100 * (b.bytes || 0)) / b.max_bytes)) : 0;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60" role="dialog" aria-modal="true" aria-label="Gateway details" data-testid="edge-detail" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col border-l border-slate-700 bg-slate-900" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-slate-800 p-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-white">{g?.name || 'Gateway'}</h2>
            {g && <p className="truncate font-mono text-[11px] text-slate-500">{g.gateway_id}</p>}
          </div>
          <div className="flex items-center gap-2">
            {g && <StatusChip status={g.status} testId="edge-detail-status" />}
            <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white" data-testid="edge-detail-close"><X className="h-5 w-5" /></button>
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-4">
          {!g && !err && <div className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading the gateway</div>}
          {err && !g && (
            <div role="alert" className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
              {err} <button type="button" onClick={load} className="ml-2 underline">Try again</button>
            </div>
          )}
          {g && (
            <>
              {g.problem && <p className="flex items-start gap-2 rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> <span className="min-w-0 break-words">{g.problem}</span></p>}
              {g.status === 'revoked' && <p className="rounded-md border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">Revoked {timeAgo(g.revoked_at)}. Abenix refuses its key for sending and for heartbeats. {canManage ? 'Make a new install command to enrol it again, its buffered readings are sent then.' : ''}</p>}
              {(g.status === 'waiting' || g.status === 'expired') && (
                <p className="rounded-md border border-sky-500/30 bg-sky-500/5 p-3 text-sm text-sky-100">
                  {g.status === 'waiting' ? 'Not started yet. Run its install command on the box.' : 'Its install command expired before the gateway started.'} {canManage ? 'Make a new install command below if you no longer have it.' : 'Someone who can manage telemetry sources can make the install command.'}
                </p>
              )}

              <section aria-label="Health">
                <h3 className="mb-1 text-sm font-medium text-white">Health</h3>
                <Row k="Last heartbeat" v={g.enrolled_at ? timeAgo(g.last_seen_at) : 'never'} />
                <Row k="Enrolled" v={g.enrolled_at ? `${timeAgo(g.enrolled_at)}${g.hostname ? ` on ${g.hostname}` : ''}` : 'not yet'} />
                <Row k="Version" v={g.version ? `Abenix Edge ${g.version}${g.platform ? `, ${g.platform}` : ''}` : 'not known yet'} />
                <Row k="Settings" v={g.config_pending ? `changed, waiting for the next heartbeat (version ${g.config_version})` : `in use (version ${g.applied_version || g.config_version})`} />
                {g.uptime_s ? <Row k="Running for" v={duration(g.uptime_s)} /> : null}
                <Row k="Link to Abenix" v={u.status ? (u.status === 'online' ? `sending, last batch ${timeAgo(u.last_ok_at ?? null)}` : u.error || u.status) : 'no report yet'} />
              </section>

              {(g.roles || []).includes('collect') && g.enrolled_at && (
                <section aria-label="Buffer">
                  <h3 className="mb-1 text-sm font-medium text-white">Store and forward buffer</h3>
                  <p className="mb-2 text-[11px] text-slate-400">Readings wait on the gateway&apos;s disk until Abenix has them, oldest first, so a lost link loses nothing within the limits.</p>
                  <Row k="Waiting to send" v={`${count(b.depth)} readings${b.oldest_age_s ? `, oldest ${duration(b.oldest_age_s)}` : ''}`} />
                  <Row k="Disk used" v={`${bytes(b.bytes)} of ${bytes(b.max_bytes)}`} />
                  <div className="my-1 h-1.5 overflow-hidden rounded bg-slate-800" aria-hidden><div className={`h-full ${fillPct > 80 ? 'bg-amber-400' : 'bg-cyan-500'}`} style={{ width: `${fillPct}%` }} /></div>
                  <Row k="Kept for" v={duration(b.max_age_s)} />
                  <Row k="Sent so far" v={`${count(b.sent)} readings`} />
                  {(b.dropped_age || b.dropped_size || b.rejected) ? (
                    <Row k="Lost" v={<span className="text-amber-200">{count(b.dropped_age)} too old, {count(b.dropped_size)} buffer full, {count(b.rejected)} refused</span>} />
                  ) : null}
                </section>
              )}

              {(g.roles || []).includes('collect') && (
                <section aria-label="Collectors">
                  <h3 className="mb-1 text-sm font-medium text-white">Collectors</h3>
                  {(g.collectors || []).length === 0 && <p className="text-xs text-slate-400">None configured.{canManage ? ' Use Change collectors to add one.' : ''}</p>}
                  <ul className="space-y-2">
                    {(g.collectors || []).map((c) => {
                      const h = (g.collector_health || []).find((x) => x.id === c.id);
                      const st = COLLECTOR_STATUS[h?.status || ''] || { label: g.enrolled_at ? 'Not reported yet' : 'Starts with the gateway', tone: 'text-slate-400' };
                      return (
                        <li key={c.id} className="rounded-md border border-slate-800 bg-slate-950/40 p-2.5 text-xs" data-testid="edge-detail-collector">
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <span className="font-medium text-slate-100">{c.name}</span>
                            <span className={st.tone}>{st.label}</span>
                          </div>
                          <p className="font-mono text-[11px] text-slate-500">{[c.asset?.group, c.asset?.node, c.asset?.device].filter(Boolean).join(' / ')}</p>
                          {h?.error && <p className="mt-1 break-words text-rose-200">{h.error}</p>}
                          {h && <p className="mt-1 text-[11px] text-slate-400">{count(h.readings)} readings, {h.readings_per_s ?? 0} a second, last {timeAgo(h.last_reading_at ?? null)}{h.bus_load_pct !== undefined ? `, bus load ${h.bus_load_pct}%` : ''}{h.last_poll_ms !== undefined ? `, poll ${h.last_poll_ms} ms` : ''}</p>}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              )}

              {(g.assets || []).length > 0 && (
                <section aria-label="Assets">
                  <h3 className="mb-1 text-sm font-medium text-white">In Telemetry</h3>
                  <ul className="space-y-1 text-xs">
                    {(g.assets || []).filter((a) => a.device).slice(0, 20).map((a) => (
                      <li key={`${a.group}/${a.node}/${a.device}`} className="flex flex-wrap items-center justify-between gap-2">
                        <Link href={telemetryHref(g, a)} className="font-mono text-cyan-300 hover:underline">{a.group} / {a.node} / {a.device}</Link>
                        <span className="text-slate-500">{a.metric_count ?? 0} signals, {a.online ? 'live' : 'quiet'}</span>
                      </li>
                    ))}
                  </ul>
                  <Link href={telemetryHref(g)} className="mt-2 inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline">Open in Telemetry <ArrowRight className="h-3 w-3" /></Link>
                </section>
              )}

              {canManage && (
                <section aria-label="Install" className="space-y-2">
                  <h3 className="text-sm font-medium text-white">Install command</h3>
                  {!showInstall ? (
                    <button type="button" onClick={() => setShowInstall(true)} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-700/50" data-testid="edge-detail-install">
                      <TerminalSquare className="h-3.5 w-3.5" /> {g.enrolled_at ? 'Move or re-enrol this gateway' : 'Show the install command'}
                    </button>
                  ) : (
                    <>
                      {g.enrolled_at && <p className="text-[11px] text-amber-200">A new command signs the gateway in again. Its current key stops working as soon as you make it.</p>}
                      <InstallPanel gateway={g} install={install} onInstall={(o) => { setInstall(o); setG(o.gateway); onChanged(); }} canManage={canManage} />
                    </>
                  )}
                </section>
              )}
            </>
          )}
        </div>
        {g && (
          <div className="flex flex-wrap gap-2 border-t border-slate-800 p-4">
            <button type="button" onClick={load} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"><RefreshCw className="h-3.5 w-3.5" /> Refresh</button>
            {canManage && (
              <>
                <button type="button" onClick={() => onEdit(g)} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-cyan-500/40 px-3 py-1.5 text-xs text-cyan-200 hover:bg-cyan-500/10" data-testid="edge-detail-edit"><Pencil className="h-3.5 w-3.5" /> Change collectors</button>
                {g.status !== 'revoked' && g.enrolled_at && (
                  <button type="button" onClick={() => setConfirm('revoke')} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs text-amber-200 hover:bg-amber-500/10" data-testid="edge-detail-revoke"><Ban className="h-3.5 w-3.5" /> Revoke</button>
                )}
                <button type="button" onClick={() => setConfirm('remove')} className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-rose-500/40 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-500/10" data-testid="edge-detail-remove"><Trash2 className="h-3.5 w-3.5" /> Remove</button>
              </>
            )}
          </div>
        )}
      </div>
      <div onClick={(e) => e.stopPropagation()}>
        <ConfirmModal
          open={confirm === 'revoke'}
          onClose={() => setConfirm(null)}
          onConfirm={revoke}
          loading={busy}
          variant="warning"
          title={`Revoke ${g?.name || 'this gateway'}?`}
          description="Abenix refuses its key at once, for sending and for heartbeats. The gateway stops its collectors and keeps what it has buffered. Make a new install command later to bring it back."
          confirmLabel="Revoke"
          confirmTestId="edge-revoke-confirm"
        />
        <ConfirmModal
          open={confirm === 'remove'}
          onClose={() => setConfirm(null)}
          onConfirm={remove}
          loading={busy}
          title={`Remove ${g?.name || 'this gateway'}?`}
          description="Its key is revoked and it disappears from this page. Stop and uninstall it on the box too."
          confirmLabel="Remove"
          confirmTestId="edge-remove-confirm"
        >
          {g?.telemetry_connection_id && (
            <label className="mt-3 flex items-start gap-2 text-xs text-slate-300">
              <input type="checkbox" className="mt-0.5 accent-rose-500" checked={removeSource} onChange={(e) => setRemoveSource(e.target.checked)} data-testid="edge-remove-source" />
              <span>Also remove its source in Telemetry. Leave this off to keep its readings and history.</span>
            </label>
          )}
        </ConfirmModal>
      </div>
    </div>
  );
}
