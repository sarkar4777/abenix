'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, CircleDashed, Loader2, ShieldCheck, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { bytes, type SourceSettings } from '@/lib/sources';

const HOST_RE = /^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$/;

export default function SourceSettingsDialog({
  settings,
  canEdit,
  onClose,
  onSaved,
}: {
  settings: SourceSettings;
  canEdit: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [hosts, setHosts] = useState(settings.host_allowlist.join('\n'));
  const [pauseAfter, setPauseAfter] = useState(settings.pause_after_failures);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const list = hosts.split(/[\n,]/).map((h) => h.trim().toLowerCase()).filter(Boolean);
  const bad = list.filter((h) => !HOST_RE.test(h));

  async function save() {
    setBusy(true);
    setErr(null);
    const r = await apiFetch('/api/sources/settings', {
      method: 'PUT',
      body: JSON.stringify({ host_allowlist: list, pause_after_failures: pauseAfter }),
      throwOnError: false,
    });
    setBusy(false);
    if (r.error) setErr(r.error);
    else onSaved();
  }

  const L = settings.limits;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="sw-settings-title">
      <div className="w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <h2 id="sw-settings-title" className="text-lg font-semibold text-white flex items-center gap-2"><ShieldCheck className="w-5 h-5 text-cyan-400" /> Allowlist and limits</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div>
            <label htmlFor="sw-hosts" className="block text-sm font-medium text-slate-200 mb-1.5">Hosts sources may fetch from</label>
            <textarea id="sw-hosts" value={hosts} onChange={(e) => setHosts(e.target.value)} rows={6} disabled={!canEdit} spellCheck={false} placeholder={'europa.eu\nlegislation.gov.uk'} className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white font-mono disabled:opacity-60" data-testid="sw-allowlist" />
            <p className={`mt-1 text-xs ${bad.length ? 'text-rose-300' : 'text-slate-500'}`}>
              {bad.length
                ? `Not host names: ${bad.slice(0, 4).join(', ')}. Use names such as europa.eu, without https:// or a path.`
                : list.length
                  ? `${list.length} host${list.length === 1 ? '' : 's'}. Each one also covers its subdomains. Anything else is refused.`
                  : 'Empty means any public host. Private and internal addresses are always refused.'}
            </p>
          </div>
          <div>
            <label htmlFor="sw-pause" className="block text-sm font-medium text-slate-200 mb-1.5">Pause a source after this many failed checks in a row</label>
            <input id="sw-pause" type="number" min={1} max={100} value={pauseAfter} disabled={!canEdit} onChange={(e) => setPauseAfter(Math.min(100, Math.max(1, Number(e.target.value) || 1)))} className="w-28 bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white disabled:opacity-60" />
          </div>
          <div>
            <div className="text-sm font-medium text-slate-200 mb-1.5">Source credentials</div>
            <ul className="grid sm:grid-cols-2 gap-1.5">
              {settings.credential_keys.map((c) => (
                <li key={c.key} className="flex items-center gap-2 text-sm text-slate-300">
                  {c.set ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <CircleDashed className="w-4 h-4 text-slate-500" />}
                  <span className="font-mono">{c.key}</span>
                  <span className="text-xs text-slate-500">{c.set ? 'set' : 'not set'}</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-slate-500">Set or change them under Admin, Tool Configuration, Source Watch. Values are encrypted and never shown here.</p>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4 text-xs text-slate-400 grid sm:grid-cols-2 gap-2">
            <div>Largest document: <span className="text-slate-200">{bytes(L.max_bytes)}</span></div>
            <div>Time limit per fetch: <span className="text-slate-200">{L.timeout_seconds} s</span></div>
            <div>Gap between requests to one host: <span className="text-slate-200">{L.host_interval_seconds} s</span></div>
            <div>Most frequent check: <span className="text-slate-200">every {L.min_cadence_minutes} minutes</span></div>
            {settings.private_targets_allowed && <div className="sm:col-span-2 text-amber-300">This install allows private addresses (SOURCE_WATCH_ALLOW_PRIVATE_TARGETS).</div>}
          </div>
          {!canEdit && <p className="text-xs text-slate-500">Changing these needs the risk.manage capability.</p>}
          {err && <p className="text-sm text-rose-300" role="alert">{err}</p>}
        </div>
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">{canEdit ? 'Cancel' : 'Close'}</button>
          {canEdit && (
            <button type="button" onClick={save} disabled={busy || bad.length > 0} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-40" data-testid="sw-settings-save">
              {busy && <Loader2 className="w-4 h-4 animate-spin" />} Save
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
