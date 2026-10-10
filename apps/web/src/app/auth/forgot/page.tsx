'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, KeyRound, Mail, MailCheck } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState<{ emailEnabled: boolean; minutes: number } | null>(null);

  useEffect(() => {
    const pre = new URLSearchParams(window.location.search).get('email');
    if (pre) setEmail(pre);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      });
      const json = await res.json();
      if (json.error) {
        setError(res.status === 422 ? 'Enter a valid email address.' : json.error.message);
        return;
      }
      setSent({ emailEnabled: !!json.data?.email_enabled, minutes: json.data?.minutes || 30 });
    } catch {
      setError('Connection failed. Check your network and try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-200 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-6 sm:p-8 shadow-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center shrink-0">
            {sent ? <MailCheck className="w-5 h-5 text-cyan-400" /> : <KeyRound className="w-5 h-5 text-cyan-400" />}
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white" data-testid="forgot-title">
              {sent ? 'Check your email' : 'Reset your password'}
            </h1>
            <p className="text-xs text-slate-500">
              {sent ? 'The link is on its way' : 'We email you a link to choose a new one'}
            </p>
          </div>
        </div>

        {sent ? (
          <div className="space-y-4" data-testid="forgot-sent">
            {sent.emailEnabled ? (
              <p className="text-sm text-slate-300">
                If an account exists for <span className="text-white font-medium">{email}</span>, an email
                with a reset link is on its way. The link works once, for {sent.minutes} minutes. Check your
                spam folder if it does not arrive in a minute.
              </p>
            ) : (
              <p role="alert" className="text-sm text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2">
                This platform cannot send email yet, so no link was sent. Ask your workspace admin to reset
                your password, or an operator to set up outgoing email.
              </p>
            )}
            <button
              type="button"
              onClick={() => setSent(null)}
              className="text-xs text-cyan-400 hover:text-cyan-300"
            >
              Use a different email
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="forgot-email" className="block text-xs font-medium text-slate-400 mb-1.5">
                Email address
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                <input
                  id="forgot-email"
                  type="email"
                  autoFocus
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    setError('');
                  }}
                  required
                  placeholder="you@company.com"
                  aria-invalid={!!error}
                  className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition outline-none"
                />
              </div>
            </div>
            {error && <p role="alert" className="text-red-400 text-xs">{error}</p>}
            <button
              type="submit"
              disabled={submitting || !email.includes('@')}
              data-testid="forgot-submit"
              className="w-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white font-semibold py-3 rounded-lg shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 transition-all text-sm disabled:opacity-50"
            >
              {submitting ? 'Sending...' : 'Email me a reset link'}
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
