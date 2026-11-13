'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Cable, MoreHorizontal, RotateCcw, UserRound } from 'lucide-react';

import { Dialog } from '@/components/Dialog';
import { api, refreshAll } from '@/lib/api';
import { toastError, toastSuccess } from '@/stores/toastStore';

export function TopBar() {
  const [staff, setStaff] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    void api.platform().then((r) => r.data && setStaff(r.data.staff_name));
  }, []);

  useEffect(() => {
    if (!menu) return undefined;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenu(false);
    };
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [menu]);

  const reset = async () => {
    const r = await api.reset();
    if (r.error) {
      toastError(r.error);
      return;
    }
    const closed = r.data?.approvals_closed ?? 0;
    const left = r.data?.approvals_left_open ?? 0;
    toastSuccess(
      'Every result cleared.'
      + (closed ? ` ${closed} open review${closed === 1 ? '' : 's'} closed in Abenix.` : '')
      + (left ? ` ${left} couldn't be closed and will expire on their own.` : ''),
    );
    setConfirmReset(false);
    refreshAll();
  };

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur">
      <div className="mx-auto max-w-[96rem] px-4 sm:px-6 h-14 flex items-center gap-3">
        <Link href="/" className="flex items-center gap-2.5 mr-auto" data-testid="home-link">
          <span className="w-8 h-8 rounded-lg bg-sky-500/15 ring-1 ring-sky-500/40 grid place-items-center">
            <Cable className="w-4 h-4 text-sky-300" />
          </span>
          <span>
            <span className="block text-sm font-bold text-white leading-tight">QuoteIQ</span>
            <span className="block text-[10px] uppercase tracking-wider text-sky-500/70">RFQ desk</span>
          </span>
        </Link>
        {staff && (
          <span className="hidden sm:inline-flex items-center gap-1.5 text-xs text-slate-400" data-testid="reviewer">
            <UserRound className="w-3.5 h-3.5" /> Reviewing as <span className="text-slate-200">{staff}</span>
          </span>
        )}
        <div className="relative" ref={menuRef}>
          <button onClick={() => setMenu((m) => !m)} aria-label="Menu" data-testid="menu"
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800">
            <MoreHorizontal className="w-5 h-5" />
          </button>
          {menu && (
            <div className="absolute right-0 mt-1 w-48 rounded-lg bg-slate-900 ring-1 ring-slate-700 py-1 shadow-xl">
              <button onClick={() => { setMenu(false); setConfirmReset(true); }} data-testid="reset-example"
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-200 hover:bg-slate-800">
                <RotateCcw className="w-4 h-4 text-slate-400" /> Reset example
              </button>
            </div>
          )}
        </div>
      </div>
      {confirmReset && (
        <Dialog
          title="Reset the example?"
          body={
            <>
              Every email goes back to waiting and every result is cleared. Reviews still open in
              Abenix are denied with the note “example reset, nothing sent”. A run still going
              finishes, but its result is dropped.
            </>
          }
          confirm="Reset"
          tone="rose"
          onConfirm={reset}
          onClose={() => setConfirmReset(false)}
        />
      )}
    </header>
  );
}
