'use client';

import { useEffect, useState } from 'react';
import { Lock, Mail, User, Users } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface InviteInfo {
  email: string;
  tenant_name: string;
  role: string;
  can_approve_decisions?: boolean;
  message?: string;
  expired: boolean;
  used?: boolean;
}

export default function AcceptInvitePage() {
  const [token, setToken] = useState('');
  const [invite, setInvite] = useState<InviteInfo | null>(null);
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('token') || '';
    setToken(t);
    if (!t) {
      setLoadError('This link has no invite token. Ask your admin to send the link again.');
      setLoading(false);
      return;
    }
    fetch(`${API_URL}/api/auth/invite/${encodeURIComponent(t)}`)
      .then((r) => r.json())
      .then((j) => {
        if (j?.data) setInvite(j.data as InviteInfo);
        else setLoadError(j?.error?.message || 'Invite not found');
      })
      .catch(() => setLoadError('Connection failed'))
      .finally(() => setLoading(false));
  }, []);

  const blocked = !!invite && (invite.expired || invite.used);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!invite || blocked) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/auth/accept-invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, full_name: fullName, password }),
      });
      const json = await res.json();
      if (json.error) {
        setError(json.error.message);
        return;
      }
      if (json.data?.access_token) {
        localStorage.setItem('access_token', json.data.access_token);
        localStorage.setItem('refresh_token', json.data.refresh_token);
        window.location.href = '/dashboard';
      }
    } catch {
      setError('Connection failed');
    } finally {
      setSubmitting(false);
    }
  }

  const inputCls =
    'w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition outline-none';

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-200 px-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl">
        {loading ? (
          <div className="flex justify-center py-8">
            <div className="w-8 h-8 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
          </div>
        ) : loadError || !invite ? (
          <div className="text-center" role="alert">
            <p className="text-red-400 text-sm">{loadError || 'Invite not found'}</p>
            <a href="/" className="inline-block mt-4 text-sm text-cyan-400 hover:text-cyan-300">
              Back to sign in
            </a>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
                <Users className="w-5 h-5 text-cyan-400" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-white" data-testid="accept-title">
                  Join {invite.tenant_name || 'the workspace'}
                </h1>
                <p className="text-xs text-slate-500">
                  You were invited as {({ admin: 'an Admin', creator: 'a Creator', user: 'a Member', member: 'a Member' } as Record<string, string>)[String(invite.role)] || invite.role}
                  {invite.can_approve_decisions || invite.role === 'admin' ? ', and you can approve decisions' : ''}.
                </p>
                {(invite.can_approve_decisions || invite.role === 'admin') && (
                  <p className="mt-1 text-xs text-slate-400" data-testid="accept-approver">That means signing off rule changes other people propose. They show up on your Approvals page.</p>
                )}
              </div>
            </div>

            {blocked ? (
              <div role="alert" className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2">
                {invite.used
                  ? 'This invite has already been used. Sign in with the account it created.'
                  : 'This invite has expired. Ask an admin for a new link.'}
                <a href="/" className="block mt-2 text-cyan-400 hover:text-cyan-300">Go to sign in</a>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="accept-email" className="block text-xs font-medium text-slate-400 mb-1.5">
                    Email Address
                  </label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                    <input id="accept-email" type="email" value={invite.email} readOnly className={`${inputCls} opacity-70`} />
                  </div>
                </div>
                <div>
                  <label htmlFor="accept-full-name" className="block text-xs font-medium text-slate-400 mb-1.5">
                    Full Name
                  </label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                    <input
                      id="accept-full-name"
                      type="text"
                      value={fullName}
                      onChange={(e) => { setFullName(e.target.value); setError(''); }}
                      required
                      placeholder="Full Name"
                      className={inputCls}
                    />
                  </div>
                </div>
                <div>
                  <label htmlFor="accept-password" className="block text-xs font-medium text-slate-400 mb-1.5">
                    Password
                  </label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                    <input
                      id="accept-password"
                      type="password"
                      value={password}
                      onChange={(e) => { setPassword(e.target.value); setError(''); }}
                      required
                      minLength={8}
                      placeholder="Password"
                      aria-describedby="accept-password-hint"
                      className={inputCls}
                    />
                  </div>
                  <p id="accept-password-hint" className="text-xs text-slate-500 mt-1">Min 8 characters</p>
                </div>

                {error && <p role="alert" className="text-red-400 text-xs">{error}</p>}

                <button
                  type="submit"
                  disabled={submitting}
                  data-testid="accept-submit"
                  className="w-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white font-semibold py-3 rounded-lg shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 transition-all text-sm disabled:opacity-50"
                >
                  {submitting ? 'Joining...' : 'Join workspace'}
                </button>
              </form>
            )}
          </>
        )}
      </div>
    </main>
  );
}
