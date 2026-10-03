'use client';

import { useEffect, useState } from 'react';
import { Loader2, PauseCircle, X } from 'lucide-react';

export default function PauseDialog({
  name,
  busy,
  onClose,
  onConfirm,
}: {
  name: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState('');
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-labelledby="pause-title">
      <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <h2 id="pause-title" className="text-base font-semibold text-white flex items-center gap-2"><PauseCircle className="w-5 h-5 text-amber-300" /> Pause {name}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1 rounded text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <div className="px-5 py-4 space-y-2">
          <p className="text-sm text-slate-400">Scheduled checks stop until someone resumes it. Snapshots and changes are kept.</p>
          <label htmlFor="pause-reason" className="block text-sm font-medium text-slate-200">Reason <span className="text-slate-500 font-normal">(shown to others)</span></label>
          <input id="pause-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Site is being redesigned" className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-white" autoFocus data-testid="pause-reason" />
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-slate-800">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800">Cancel</button>
          <button type="button" onClick={() => onConfirm(reason)} disabled={busy} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium bg-amber-500 text-slate-950 hover:bg-amber-400 disabled:opacity-40" data-testid="pause-confirm">
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Pause
          </button>
        </div>
      </div>
    </div>
  );
}
