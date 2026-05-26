'use client';

import { useEffect, useState } from 'react';

export default function OAuthCallback() {
  const [status, setStatus] = useState<'working' | 'error'>('working');
  const [message, setMessage] = useState('Finishing sign-in...');

  useEffect(() => {
    const hash = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1)
      : window.location.hash;
    const params = new URLSearchParams(hash);
    const access = params.get('access_token');
    const refresh = params.get('refresh_token');
    const returnTo = params.get('return_to') || '/dashboard';

    if (!access || !refresh) {
      setStatus('error');
      setMessage('Sign-in did not return credentials. Try again from the login page.');
      return;
    }

    try {
      localStorage.setItem('access_token', access);
      localStorage.setItem('refresh_token', refresh);
      // Token shape is identical to /api/auth/login response — the rest
      // of the app reads localStorage on first paint after redirect.
      window.location.replace(returnTo);
    } catch {
      setStatus('error');
      setMessage('Browser blocked localStorage. Enable cookies and try again.');
    }
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-200">
      <div className="text-center">
        <div className="w-10 h-10 mx-auto mb-4 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
        <p className={status === 'error' ? 'text-red-400' : 'text-slate-300'}>
          {message}
        </p>
        {status === 'error' && (
          <a
            href="/"
            className="inline-block mt-4 text-sm text-cyan-400 hover:text-cyan-300"
          >
            Back to sign in
          </a>
        )}
      </div>
    </main>
  );
}
