'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Copy, Download, Loader2, Search, X } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { KIND_LABEL, bytes, downloadRaw, when, type Snapshot } from '@/lib/sources';

function Highlighted({ text, needle }: { text: string; needle: string }) {
  if (!needle) return <>{text}</>;
  const parts: ReactNode[] = [];
  const lower = text.toLowerCase();
  const n = needle.toLowerCase();
  let i = 0;
  let k = 0;
  while (k < 2000) {
    const j = lower.indexOf(n, i);
    if (j < 0) break;
    parts.push(text.slice(i, j));
    parts.push(<mark key={k++} className="bg-amber-400/40 text-amber-50 rounded-sm">{text.slice(j, j + n.length)}</mark>);
    i = j + n.length;
  }
  parts.push(text.slice(i));
  return <>{parts}</>;
}

export default function SnapshotViewer({ id, onClose }: { id: string; onClose: () => void }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loadingFull, setLoadingFull] = useState(false);
  const [find, setFind] = useState('');
  const [dlErr, setDlErr] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    setSnap(null);
    setErr(null);
    apiFetch<Snapshot>(`/api/sources/snapshots/${id}`, { throwOnError: false }).then((r) => {
      if (!live) return;
      if (r.error || !r.data) setErr(r.error || 'Could not load the snapshot.');
      else setSnap(r.data);
    });
    return () => {
      live = false;
    };
  }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const matches = useMemo(() => {
    if (!find || !snap?.text) return 0;
    return snap.text.toLowerCase().split(find.toLowerCase()).length - 1;
  }, [find, snap]);

  async function loadFull() {
    setLoadingFull(true);
    const r = await apiFetch<Snapshot>(`/api/sources/snapshots/${id}?full=true`, { throwOnError: false });
    setLoadingFull(false);
    if (r.data) setSnap(r.data);
  }

  async function download() {
    setDownloading(true);
    setDlErr(await downloadRaw(id));
    setDownloading(false);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="snap-title">
      <div className="w-full max-w-5xl h-[90vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-start justify-between gap-3 px-6 py-4 border-b border-slate-800">
          <div className="min-w-0">
            <h2 id="snap-title" className="text-lg font-semibold text-white truncate">{snap?.title || 'Snapshot'}</h2>
            {snap && (
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400 mt-1">
                <span>{when(snap.fetched_at)}</span>
                <span>{KIND_LABEL[snap.kind]}</span>
                <span>HTTP {snap.http_status}</span>
                <span>{bytes(snap.bytes)}</span>
                <span>reader {snap.parser_version}</span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 font-mono hover:text-white"
                  title="Copy the SHA-256 of the original bytes"
                  onClick={() => {
                    navigator.clipboard?.writeText(snap.content_sha256).then(() => {
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    });
                  }}
                >
                  <Copy className="w-3 h-3" /> {copied ? 'copied' : `sha256 ${snap.content_sha256.slice(0, 16)}…`}
                </button>
              </div>
            )}
            {snap && <a href={snap.url} target="_blank" rel="noopener noreferrer" className="text-xs text-cyan-300 hover:underline break-all">{snap.url}</a>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white shrink-0"><X className="w-5 h-5" /></button>
        </div>
        {err ? (
          <div className="p-6 text-sm text-rose-200">{err}</div>
        ) : !snap ? (
          <div className="p-6 space-y-2" aria-busy="true">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-3 rounded bg-slate-800/60 animate-pulse" style={{ width: `${95 - i * 9}%` }} />)}</div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 px-6 py-3 border-b border-slate-800">
              <div className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950 px-3 flex-1 min-w-[200px] max-w-sm">
                <Search className="w-4 h-4 text-slate-500" />
                <input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Find in this snapshot…" className="flex-1 bg-transparent py-1.5 text-sm text-white outline-none" aria-label="Find in snapshot" />
              </div>
              {find && <span className="text-xs text-slate-400">{matches} match{matches === 1 ? '' : 'es'}</span>}
              <div className="ml-auto flex items-center gap-2">
                {snap.text_truncated && (
                  <button type="button" onClick={loadFull} disabled={loadingFull} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-slate-300 border border-slate-700 hover:bg-slate-800">
                    {loadingFull && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Load the full text
                  </button>
                )}
                <button type="button" onClick={download} disabled={downloading} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-cyan-200 border border-cyan-500/40 hover:bg-cyan-500/10" data-testid="snapshot-download">
                  {downloading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Download the original
                </button>
              </div>
            </div>
            {dlErr && <p className="px-6 pt-2 text-xs text-rose-300">{dlErr}</p>}
            {snap.notes.map((n) => <p key={n} className="px-6 pt-2 text-xs text-amber-300">{n}</p>)}
            <pre className="flex-1 overflow-auto m-4 mt-3 rounded-lg border border-slate-800 bg-slate-950 p-4 text-xs leading-5 text-slate-200 whitespace-pre-wrap break-words" data-testid="snapshot-text">
              {snap.text ? <Highlighted text={snap.text} needle={find} /> : '(no readable text)'}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}
