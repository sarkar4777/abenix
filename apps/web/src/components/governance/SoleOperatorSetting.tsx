'use client';

import { useState } from 'react';
import { UserCheck } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { useApi } from '@/hooks/useApi';
import ConfirmModal from '@/components/ui/ConfirmModal';

interface Settings { sole_operator_signoff: boolean }

// the one-person workspace switch for rule changes and risk tier changes
export default function SoleOperatorSetting({ canChange }: { canChange: boolean }) {
  const { data, error, isLoading, mutate } = useApi<Settings>('/api/governance/settings');
  const [ask, setAsk] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const on = !!data?.sole_operator_signoff;

  async function save(next: boolean) {
    setBusy(true);
    setErr(null);
    const r = await apiFetch<Settings>('/api/governance/settings', { method: 'PUT', body: JSON.stringify({ sole_operator_signoff: next }), throwOnError: false });
    setBusy(false);
    setAsk(null);
    if (r.error) setErr(r.error);
    else mutate();
  }

  return (
    <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="sole-operator-setting">
      <div className="flex flex-wrap items-start gap-3">
        <UserCheck className="w-5 h-5 text-cyan-400 mt-0.5" />
        <div className="flex-1 min-w-[220px]">
          <h3 className="text-sm font-semibold text-white">Let the only approver sign their own change</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-3xl">
            Rule changes and risk tier changes need someone other than the author to approve them. In a workspace where nobody else can, the author would be stuck.
            With this on, the author can approve it themselves after writing a reason. It is recorded as self-approved, shown that way wherever the sign-off appears, and every admin is notified.
            As soon as a second person can approve, this way is closed and they must ask that person.
          </p>
          {error && !data && <p className="mt-2 text-xs text-rose-300" role="alert">The setting could not be loaded. Reload the page to try again.</p>}
          {err && <p className="mt-2 text-xs text-rose-300" role="alert">{err}</p>}
          {!canChange && data && <p className="mt-2 text-[11px] text-slate-500">Only an admin can change this.</p>}
        </div>
        <label className={`inline-flex items-center gap-2 text-sm ${canChange ? 'cursor-pointer' : 'opacity-60'}`}>
          <span className={on ? 'text-emerald-300' : 'text-slate-400'}>{isLoading && !data ? 'Loading…' : on ? 'On' : 'Off'}</span>
          <button
            type="button"
            role="switch"
            aria-checked={on}
            aria-label="Let the only approver sign their own change"
            disabled={!canChange || !data || busy}
            onClick={() => setAsk(!on)}
            className={`relative h-6 w-11 rounded-full transition ${on ? 'bg-emerald-500' : 'bg-slate-700'} disabled:cursor-not-allowed`}
            data-testid="sole-operator-toggle"
          >
            <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${on ? 'left-[22px]' : 'left-0.5'}`} />
          </button>
        </label>
      </div>
      <ConfirmModal
        open={ask !== null}
        onClose={() => setAsk(null)}
        onConfirm={() => ask !== null && save(ask)}
        loading={busy}
        variant="warning"
        icon={UserCheck}
        title={ask ? 'Let the only approver sign their own change?' : 'Stop the only approver signing their own change?'}
        description={ask
          ? 'Where nobody else can approve a rule change or a risk tier change, the author can sign it off with a written reason. Each one is recorded and the admins are told. This change is recorded in the audit log.'
          : 'Where nobody else can approve, rule changes and risk tier changes wait until you invite someone who can. Anything already approved stays approved. This change is recorded in the audit log.'}
        confirmLabel={ask ? 'Turn on' : 'Turn off'}
        confirmTestId="sole-operator-confirm"
      />
    </section>
  );
}
