'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Copy, Loader2, RefreshCw } from 'lucide-react';
import { edgeCall, type Gateway, type InstallOut } from './model';

const TABS = [
  { id: 'docker_run', label: 'Docker', help: 'One command on any Linux box with Docker. The data volume keeps the buffer and the gateway key across restarts.' },
  { id: 'compose', label: 'Docker Compose', help: 'Save as compose.yaml on the box, then run docker compose up -d.' },
  { id: 'kubernetes', label: 'Kubernetes', help: 'Save as edge.yaml and run kubectl apply -f edge.yaml. It makes a namespace, a secret and one pod with a 2 GB volume.' },
  { id: 'systemd', label: 'Linux IPC or Raspberry Pi', help: 'Paste into a shell on the box. systemd starts the gateway at boot and restarts it if it stops. Works on amd64 and arm64 (64-bit Raspberry Pi OS).' },
] as const;
type TabId = (typeof TABS)[number]['id'];

export function CopyBlock({ text, testId, label }: { text: string; testId: string; label: string }) {
  const [done, setDone] = useState(false);
  const [failed, setFailed] = useState(false);
  const copy = () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard) { setFailed(true); return; }
    navigator.clipboard.writeText(text).then(() => {
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    }).catch(() => setFailed(true));
  };
  return (
    <div className="min-w-0">
      <div className="relative min-w-0">
        <pre className="max-h-72 min-w-0 overflow-auto whitespace-pre rounded-md border border-slate-800 bg-slate-950 p-3 pr-20 font-mono text-[11px] leading-relaxed text-emerald-200" data-testid={testId} aria-label={label}>{text}</pre>
        <button type="button" onClick={copy} className="absolute right-2 top-2 inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] text-slate-100 hover:bg-slate-700" data-testid={`${testId}-copy`}>
          {done ? <CheckCircle2 className="h-3 w-3 text-emerald-300" /> : <Copy className="h-3 w-3" />}
          {done ? 'Copied' : 'Copy'}
        </button>
      </div>
      {failed && <p className="mt-1 text-[11px] text-amber-300">This browser blocked copying. Select the text and copy it by hand.</p>}
    </div>
  );
}

export default function InstallPanel({ gateway, install, onInstall, canManage }: {
  gateway: Gateway;
  install: InstallOut | null;
  onInstall: (out: InstallOut) => void;
  canManage: boolean;
}) {
  const [tab, setTab] = useState<TabId>('docker_run');
  const [url, setUrl] = useState(install?.platform_url || '');
  const [urls, setUrls] = useState<{ label: string; url: string }[]>(install?.platform_urls || []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    edgeCall<{ platform_urls: { label: string; url: string }[] }>('/api/edge/install/urls').then((r) => {
      if (!live) return;
      const list = r.data?.platform_urls || [];
      setUrls(list);
      setUrl((cur) => cur || list[0]?.url || process.env.NEXT_PUBLIC_API_URL || window.location.origin);
    });
    return () => { live = false; };
  }, []);

  const urlProblem = url && !/^https?:\/\/[^\s/]+/.test(url) ? 'Use the full address with http:// or https://, such as https://abenix.example.com' : null;

  const make = async () => {
    if (!url) { setErr('Give the address the gateway uses to reach Abenix, such as https://abenix.example.com'); return; }
    if (urlProblem) return;
    setBusy(true);
    setErr(null);
    const r = await edgeCall<InstallOut>(`/api/edge/gateways/${gateway.id}/install`, 'POST', { platform_url: url });
    setBusy(false);
    if (r.error || !r.data) { setErr(r.error); return; }
    onInstall(r.data);
  };

  if (!canManage) {
    return <p className="text-sm text-slate-300">Install commands carry a one-time enrolment token, so only people who can manage telemetry sources can make them. An admin can give you that under Admin, Permissions.</p>;
  }

  return (
    <div className="space-y-3" data-testid="edge-install">
      <div className="min-w-0">
        <label htmlFor="edge-platform-url" className="text-xs font-medium text-slate-200">Address the gateway uses to reach Abenix <span className="text-rose-300">*</span></label>
        <p className="text-[11px] text-slate-400">It must work from the box itself, over the site network, VPN or mobile data. Use https outside a lab.</p>
        <div className="mt-1 flex flex-col gap-2 sm:flex-row">
          <input id="edge-platform-url" className={`min-w-0 flex-1 rounded-md border bg-slate-950 px-2.5 py-2 text-sm text-white ${urlProblem ? 'border-rose-500/60' : 'border-slate-700'}`} value={url} onChange={(e) => setUrl(e.target.value.trim())} placeholder="https://abenix.example.com" data-testid="edge-platform-url" aria-invalid={!!urlProblem} />
          <button type="button" onClick={make} disabled={busy || !!urlProblem} className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50" data-testid="edge-make-install">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {install ? 'Make a new command' : 'Make the install command'}
          </button>
        </div>
        {urls.length > 1 && (
          <div className="mt-1 flex flex-wrap gap-2 text-[11px]">
            {urls.map((u) => (
              <button key={u.url} type="button" onClick={() => setUrl(u.url)} className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200">
                {u.label}: <span className="font-mono">{u.url}</span>
              </button>
            ))}
          </div>
        )}
        {urlProblem && <p role="alert" className="mt-1 text-[11px] text-rose-300">{urlProblem}</p>}
        {err && <p role="alert" className="mt-1 text-[11px] text-rose-300" data-testid="edge-install-error">{err}</p>}
      </div>

      {install && (
        <>
          <div className="flex items-start gap-2 rounded-md border border-amber-600/40 bg-amber-900/20 p-2.5 text-[12px] text-amber-100">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p className="min-w-0">
              The command holds a one-time enrolment token. It works once, until {new Date(install.expires_at).toLocaleString()}. After the gateway enrols it gets its own key and the token is useless. Making a new command cancels this one.
            </p>
          </div>
          <div className="scrollbar-none flex gap-1 overflow-x-auto border-b border-slate-800" role="tablist" aria-label="How to install">
            {TABS.map((t) => (
              <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)} className={`whitespace-nowrap border-b-2 px-3 py-2 text-xs ${tab === t.id ? 'border-cyan-400 text-cyan-200' : 'border-transparent text-slate-400 hover:text-slate-200'}`} data-testid={`edge-install-tab-${t.id}`}>
                {t.label}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-400">{TABS.find((t) => t.id === tab)?.help}</p>
          <CopyBlock text={install[tab]} testId={`edge-install-${tab}`} label={`${TABS.find((t) => t.id === tab)?.label} install command`} />
          {(install.needs.host_network || install.needs.devices.length > 0 || install.needs.folders.length > 0) && (
            <ul className="list-disc space-y-1 pl-5 text-[11px] text-slate-300">
              {install.needs.host_network && (
                <li>
                  A CAN interface lives on the host, so the gateway uses the host network. Bring the interface up first:
                  <code className="ml-1 break-all text-cyan-200">{install.can_setup}</code>
                </li>
              )}
              {install.needs.devices.length > 0 && <li>Serial devices passed in: <code className="break-all text-cyan-200">{install.needs.devices.join(', ')}</code>. On Kubernetes this needs a privileged pod on that node.</li>}
              {install.needs.folders.length > 0 && <li>Folders mounted read only: <code className="break-all text-cyan-200">{install.needs.folders.join(', ')}</code></li>}
            </ul>
          )}
          <p className="text-[11px] text-slate-500">{install.arm64_note}</p>
        </>
      )}
    </div>
  );
}
