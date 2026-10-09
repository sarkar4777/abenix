'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Loader2, ShieldCheck } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { gateWarning, improvementsApi, plural, type GateState } from '@/lib/improvements';

// Owner switch: require the improvement tests to pass before changes to the live agent go through. Off by default.
export default function GateToggle({ agentId, gate, canManage, onChanged }: {
  agentId: string; gate: GateState; canManage: boolean; onChanged: (g: GateState) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function apply(on: boolean) {
    setBusy(true);
    setErr(null);
    const r = await improvementsApi.setGate(agentId, on);
    setBusy(false);
    setConfirm(null);
    if (r.error || !r.data) { setErr(r.error || 'The setting did not change. Try again.'); return; }
    onChanged(r.data);
  }

  function flip() {
    if (gate.gating) { apply(false); return; }
    const warn = gateWarning(gate);
    if (warn) setConfirm(warn); else apply(true);
  }

  const blocked = !canManage
    ? "Only the agent's owner, or someone with the improvements.propose permission, can change this."
    : !gate.accepted ? 'Accept at least one suggested case first.' : undefined;

  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 p-3" data-testid="improvement-gate">
      <div className="flex items-start gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={gate.gating}
          aria-labelledby="improvement-gate-label"
          disabled={!!blocked || busy}
          title={blocked}
          onClick={flip}
          className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50 ${gate.gating ? 'bg-cyan-500' : 'bg-slate-600'}`}
          data-testid="improvement-gate-switch"
        >
          <span className={`inline-block h-4 w-4 rounded-full bg-white transition ${gate.gating ? 'translate-x-4' : 'translate-x-0.5'}`} />
        </button>
        <div className="min-w-0 text-xs">
          <p id="improvement-gate-label" className="flex items-center gap-1.5 font-medium text-slate-200">
            Require these tests to pass before changes go live {busy && <Loader2 className="h-3 w-3 animate-spin" />}
          </p>
          <p className="mt-0.5 text-slate-400">
            Off by default. Accepted cases always run when a fix is proven. Turn this on once they pass, so a later edit cannot bring the same mistakes back.
          </p>
          <p className="mt-1 text-slate-500" data-testid="improvement-gate-status">
            {plural(gate.accepted, 'accepted test')}
            {gate.failing === null ? ', not run yet' : `, ${gate.failing} failing in the last run`}.
            {gate.suite_id && (
              <> <Link href={`/evals/${encodeURIComponent(gate.suite_id)}`} className="text-cyan-300 hover:underline">Run them</Link></>
            )}
          </p>
          {blocked && <p className="mt-1 text-slate-500">{blocked}</p>}
          {err && <p className="mt-1 text-rose-300" role="alert">{err}</p>}
        </div>
      </div>
      <ConfirmModal
        open={!!confirm}
        onClose={() => setConfirm(null)}
        onConfirm={() => apply(true)}
        title="Require these tests before changes go live?"
        description={confirm || ''}
        confirmLabel="Turn it on"
        variant="warning"
        loading={busy}
        confirmTestId="improvement-gate-confirm"
        icon={ShieldCheck}
      />
    </div>
  );
}
