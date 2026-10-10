'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, Eye, EyeOff, KeyRound, Lock } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const MIN_LEN = 8;

export default function ResetPasswordPage() {
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [linkBroken, setLinkBroken] = useState(false);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('token') || '';
    setToken(t);
    if (!t) setLinkBroken(true);
  }, []);

  const tooShort = password.length > 0 && password.length < MIN_LEN;
  const mismatch = confirm.length > 0 && confirm !== password;
  const canSubmit = password.length >= MIN_LEN && confirm === password && !submitting;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      });
      const json = await res.json();
      if (json.error) {
        setError(json.error.message);
        if (/expired|already used/i.test(json.error.message)) setLinkBroken(true);
        return;
      }
      const q = new URLSearchParams({ reset: 'done' });
      if (json.data?.email) q.set('email', json.data.email);
      window.location.href = `/?${q.toString()}`;
    } catch {
      setError('Connection failed. Check your network and try again.');
    } finally {
      setSubmitting(false);
    }
  }

  const inputCls =
    'w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-10 py-3 text-white text-sm placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition outline-none';

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-200 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0">
            <KeyRound className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white" data-testid="reset-title">Choose a new password</h1>
            <p className="text-xs text-slate-500">Every device signed in to your account is signed out</p>
          </div>
        </div>

        {linkBroken ? (
          <div role="alert" className="space-y-3" data-testid="reset-link-broken">
            <p className="text-sm text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2">
              {error || 'This link is not complete. Open the link from the email again, or ask for a new one.'}
            </p>
            <a href="/auth/forgot" className="inline-block text-sm text-cyan-400 hover:text-cyan-300">
              Send me a new link
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="reset-password" className="block text-xs font-medium text-slate-400 mb-1.5">
                New password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                <input
                  id="reset-password"
                  type={show ? 'text' : 'password'}
                  autoFocus
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    setError('');
                  }}
                  aria-invalid={tooShort}
                  aria-describedby="reset-password-hint"
                  className={inputCls}
                />
                <button
                  type="button"
                  onClick={() => setShow(!show)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                >
                  {show ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p id="reset-password-hint" className={`text-xs mt-1 ${tooShort ? 'text-amber-300' : 'text-slate-500'}`}>
                At least {MIN_LEN} characters
              </p>
            </div>
            <div>
              <label htmlFor="reset-confirm" className="block text-xs font-medium text-slate-400 mb-1.5">
                Type it again
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                <input
                  id="reset-confirm"
                  type={show ? 'text' : 'password'}
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => {
                    setConfirm(e.target.value);
                    setError('');
                  }}
                  aria-invalid={mismatch}
                  className={inputCls}
                />
              </div>
              {mismatch && <p className="text-xs mt-1 text-amber-300">The two passwords are not the same</p>}
            </div>
            {error && <p role="alert" className="text-red-400 text-xs">{error}</p>}
            <button
              type="submit"
              disabled={!canSubmit}
              data-testid="reset-submit"
              className="w-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white font-semibold py-3 rounded-lg shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 transition-all text-sm disabled:opacity-50"
            >
              {submitting ? 'Saving...' : 'Save new password'}
            </button>
          </form>
        )}

        <a href="/" className="mt-6 inline-flex items-center gap-1 text-xs text-slate-400 hover:text-slate-200">
          <ArrowLeft className="w-3 h-3" aria-hidden="true" /> Back to sign in
        </a>
      </div>
    </main>
  );
}
