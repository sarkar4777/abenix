'use client';

import { useState } from 'react';
import { Check, Copy, KeyRound, Loader2, ShieldCheck, ShieldOff } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess } from '@/stores/toastStore';

interface Status {
  enabled: boolean;
  enabled_at: string | null;
  recovery_codes_left: number;
  has_password: boolean;
}

interface Setup {
  secret: string;
  otpauth_uri: string;
  qr_svg: string | null;
}

const inputCls =
  'w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50';

function errText(e: unknown, fallback: string) {
  return e instanceof Error && e.message ? e.message : fallback;
}

export default function TwoFactorPanel() {
  const { data: status, mutate, isLoading } = useApi<Status>('/api/settings/2fa');
  const [password, setPassword] = useState('');
  const [setup, setSetup] = useState<Setup | null>(null);
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [disabling, setDisabling] = useState(false);
  const [copied, setCopied] = useState(false);

  const reset = () => {
    setPassword('');
    setCode('');
    setErr('');
  };

  const begin = async () => {
    setBusy(true);
    setErr('');
    try {
      const r = await apiFetch<Setup>('/api/settings/2fa/setup', {
        method: 'POST',
        body: JSON.stringify({ password }),
      });
      if (r.data) setSetup(r.data);
      setPassword('');
    } catch (e) {
      setErr(errText(e, 'Could not start. Try again.'));
    }
    setBusy(false);
  };

  const confirm = async () => {
    setBusy(true);
    setErr('');
    try {
      const r = await apiFetch<Status & { recovery_codes: string[] }>('/api/settings/2fa/enable', {
        method: 'POST',
        body: JSON.stringify({ code }),
      });
      setCodes(r.data?.recovery_codes || []);
      setSetup(null);
      setCode('');
      mutate();
      toastSuccess('Two-step sign-in is on');
    } catch (e) {
      setErr(errText(e, 'That code did not match.'));
    }
    setBusy(false);
  };

  const turnOff = async () => {
    setBusy(true);
    setErr('');
    try {
      await apiFetch('/api/settings/2fa/disable', {
        method: 'POST',
        body: JSON.stringify({ password, code }),
      });
      setDisabling(false);
      setCodes(null);
      reset();
      mutate();
      toastSuccess('Two-step sign-in is off');
    } catch (e) {
      setErr(errText(e, 'Could not turn it off.'));
    }
    setBusy(false);
  };

  const copyCodes = async () => {
    if (!codes) return;
    try {
      await navigator.clipboard.writeText(codes.join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  return (
    <section
      className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6 space-y-4"
      data-testid="twofa-panel"
      aria-labelledby="twofa-title"
    >
      <div className="flex flex-wrap items-center gap-2">
        <KeyRound className="w-4 h-4 text-cyan-400" aria-hidden="true" />
        <h2 id="twofa-title" className="text-sm font-semibold text-white">Two-step sign-in</h2>
        {status && (
          <span
            data-testid="twofa-state"
            className={`ml-auto text-[11px] px-2 py-0.5 rounded border ${
              status.enabled
                ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
                : 'text-slate-400 bg-slate-700/30 border-slate-600/40'
            }`}
          >
            {status.enabled ? 'On' : 'Off'}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-400">
        After your password, sign-in asks for a 6-digit code from an authenticator app on your phone, such as
        Google Authenticator, Microsoft Authenticator or 1Password. Someone who learns your password still
        cannot get in.
      </p>

      {isLoading && !status ? (
        <div className="h-9 w-48 bg-slate-800 animate-pulse rounded" />
      ) : codes ? (
        <div className="space-y-3" data-testid="twofa-recovery">
          <p className="text-sm text-amber-200">
            Save these recovery codes somewhere safe. Each one signs you in once if you lose your phone. They are
            not shown again.
          </p>
          <ul className="grid grid-cols-2 gap-2 font-mono text-sm text-slate-100 bg-slate-900 border border-slate-700 rounded-lg p-3">
            {codes.map((c) => (
              <li key={c} data-testid="twofa-recovery-code">{c}</li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={copyCodes}
              className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs rounded-lg inline-flex items-center gap-1.5"
            >
              {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? 'Copied' : 'Copy codes'}
            </button>
            <button
              type="button"
              onClick={() => setCodes(null)}
              data-testid="twofa-recovery-done"
              className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-medium rounded-lg"
            >
              I saved them
            </button>
          </div>
        </div>
      ) : status?.enabled ? (
        disabling ? (
          <div className="space-y-3">
            {status.has_password && (
              <div>
                <label htmlFor="twofa-off-password" className="block text-xs text-slate-400 mb-1">Your password</label>
                <input
                  id="twofa-off-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setErr(''); }}
                  className={inputCls}
                />
              </div>
            )}
            <div>
              <label htmlFor="twofa-off-code" className="block text-xs text-slate-400 mb-1">Code from your app, or a recovery code</label>
              <input
                id="twofa-off-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => { setCode(e.target.value); setErr(''); }}
                className={inputCls}
              />
            </div>
            {err && <p role="alert" className="text-xs text-rose-300">{err}</p>}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={turnOff}
                disabled={busy || !code.trim() || (status.has_password && !password)}
                data-testid="twofa-disable-confirm"
                className="px-3 py-1.5 bg-rose-500/80 hover:bg-rose-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg inline-flex items-center gap-1.5"
              >
                {busy && <Loader2 className="w-3 h-3 animate-spin" />}
                Turn off two-step sign-in
              </button>
              <button type="button" onClick={() => { setDisabling(false); reset(); }} className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs text-emerald-300 inline-flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5" /> On since{' '}
              {status.enabled_at ? new Date(status.enabled_at).toLocaleDateString() : 'recently'}.{' '}
              {status.recovery_codes_left} recovery codes left.
            </p>
            <button
              type="button"
              onClick={() => setDisabling(true)}
              data-testid="twofa-disable"
              className="ml-auto px-3 py-1.5 border border-slate-600 hover:border-rose-500/60 text-slate-200 text-xs rounded-lg inline-flex items-center gap-1.5"
            >
              <ShieldOff className="w-3 h-3" /> Turn off
            </button>
          </div>
        )
      ) : setup ? (
        <div className="space-y-4" data-testid="twofa-setup">
          <ol className="text-xs text-slate-300 list-decimal pl-4 space-y-1">
            <li>Open your authenticator app and add an account.</li>
            <li>Scan this code, or type the key below by hand.</li>
            <li>Type the 6-digit code the app shows to finish.</li>
          </ol>
          <div className="flex flex-col sm:flex-row gap-4 items-start">
            {setup.qr_svg && (
              <img src={setup.qr_svg} alt="QR code to add Abenix to your authenticator app" className="w-40 h-40 rounded-lg bg-white p-1" />
            )}
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-xs text-slate-400">Key</p>
              <code data-testid="twofa-secret" className="block break-all text-sm text-slate-100 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2">
                {setup.secret.replace(/(.{4})/g, '$1 ').trim()}
              </code>
              <p className="text-[11px] text-slate-500">Time based, 6 digits, every 30 seconds.</p>
            </div>
          </div>
          <div>
            <label htmlFor="twofa-code" className="block text-xs text-slate-400 mb-1">Code from your app</label>
            <input
              id="twofa-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              value={code}
              onChange={(e) => { setCode(e.target.value); setErr(''); }}
              className={`${inputCls} max-w-[12rem] tracking-widest`}
            />
          </div>
          {err && <p role="alert" className="text-xs text-rose-300">{err}</p>}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={confirm}
              disabled={busy || code.replace(/\D/g, '').length !== 6}
              data-testid="twofa-enable-confirm"
              className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 text-xs font-medium rounded-lg inline-flex items-center gap-1.5"
            >
              {busy && <Loader2 className="w-3 h-3 animate-spin" />}
              Turn on
            </button>
            <button type="button" onClick={() => { setSetup(null); reset(); }} className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200">
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {status?.has_password && (
            <div>
              <label htmlFor="twofa-password" className="block text-xs text-slate-400 mb-1">Confirm your password to start</label>
              <input
                id="twofa-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setErr(''); }}
                className={`${inputCls} max-w-sm`}
              />
            </div>
          )}
          {err && <p role="alert" className="text-xs text-rose-300">{err}</p>}
          <button
            type="button"
            onClick={begin}
            disabled={busy || (!!status?.has_password && !password)}
            data-testid="twofa-start"
            className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 text-xs font-medium rounded-lg inline-flex items-center gap-1.5"
          >
            {busy && <Loader2 className="w-3 h-3 animate-spin" />}
            Set up two-step sign-in
          </button>
        </div>
      )}
    </section>
  );
}
