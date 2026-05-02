'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, BookOpen } from 'lucide-react';

/**
 * Startup-time badge that signals whether the tenant has a KB ready.
 *
 * The standalone API exposes /api/industrial-iot/kb-status which calls
 * abenix-api/api/knowledge-engines and checks for at least one entry.
 * If none, we surface a yellow notice so users understand why
 * adjudications cite "standard terms" instead of tenant-specific docs.
 */
export default function KbBadge() {
  const [state, setState] = useState<'checking' | 'available' | 'missing'>('checking');
  const [reason, setReason] = useState<string>('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch('/api/industrial-iot/kb-status');
        if (!r.ok) {
          if (!cancelled) { setState('missing'); setReason(`http_${r.status}`); }
          return;
        }
        const j = await r.json();
        if (cancelled) return;
        const d = j?.data ?? {};
        if (d.available) {
          setState('available');
        } else {
          setState('missing');
          setReason(d.reason ?? 'no_kb');
        }
      } catch {
        if (!cancelled) { setState('missing'); setReason('probe_error'); }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (state === 'checking') return null;

  if (state === 'available') {
    return (
      <div className="inline-flex items-center gap-1.5 text-[11px] text-emerald-300/90 bg-emerald-500/10 border border-emerald-500/30 rounded-md px-2 py-1">
        <BookOpen className="w-3 h-3" />
        Knowledge base linked — adjudications cite tenant docs.
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-1.5 text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-md px-2 py-1">
      <AlertTriangle className="w-3 h-3" />
      KB Not Available — Using Defaults
      {reason && <span className="text-amber-300/60 ml-1">({reason})</span>}
    </div>
  );
}
