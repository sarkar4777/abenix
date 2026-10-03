'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowRight,
  Eye,
  EyeOff,
  Lock,
  Mail,
  Shield,
  Sparkles,
  User,
  Users,
} from 'lucide-react';
import { readSignInParams } from '@/lib/auth-redirect';

type Tab = 'login' | 'register';

interface FormData {
  email: string;
  password: string;
  full_name: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function useTypingAnimation(text: string, speed = 80) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    setDisplayed('');
    setDone(false);
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setDisplayed(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(interval);
        setDone(true);
      }
    }, speed);
    return () => clearInterval(interval);
  }, [text, speed]);

  return { displayed, done };
}

export default function AuthCard() {
  // Default to login — repeat visitors are the common case.
  const [tab, setTab] = useState<Tab>('login');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState<FormData>({
    email: '',
    password: '',
    full_name: '',
  });
  const [ssoProviders, setSsoProviders] = useState<string[]>([]);
  const [returnTo, setReturnTo] = useState('/dashboard');
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    const params = readSignInParams();
    setReturnTo(params.returnTo);
    setSessionExpired(params.expired);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/auth/oidc/providers`)
      .then((r) => r.json())
      .then((j) => {
        if (!cancelled) setSsoProviders((j?.data?.providers || []) as string[]);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const { displayed: titleText, done: titleDone } = useTypingAnimation('Access Portal', 90);

  function updateField(field: keyof FormData, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError('');
  }

  const submitLogin = useCallback(async (email: string, password: string) => {
    setTab('login');
    setForm({ email, password, full_name: '' });
    setLoading(true);
    setError('');

    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const json = await res.json();

      if (json.error) {
        setError(json.error.message);
        return;
      }

      if (json.data?.access_token) {
        localStorage.setItem('access_token', json.data.access_token);
        localStorage.setItem('refresh_token', json.data.refresh_token);
        window.location.href = returnTo;
      }
    } catch {
      setError('Connection failed');
    } finally {
      setLoading(false);
    }
  }, [returnTo]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const endpoint =
        tab === 'register' ? '/api/auth/register' : '/api/auth/login';
      const body =
        tab === 'register'
          ? { email: form.email, password: form.password, full_name: form.full_name }
          : { email: form.email, password: form.password };

      const res = await fetch(`${API_URL}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const json = await res.json();

      if (json.error) {
        setError(json.error.message);
        return;
      }

      if (json.data?.access_token) {
        localStorage.setItem('access_token', json.data.access_token);
        localStorage.setItem('refresh_token', json.data.refresh_token);
        window.location.href = returnTo;
      }
    } catch {
      setError('Connection failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 30, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.6, delay: 0.3 }}
      className="w-full max-w-md"
    >
      <div
        className="relative rounded-2xl p-[1px] shadow-2xl shadow-black/50"
        style={{
          background: 'linear-gradient(270deg, #06B6D4, #A855F7, #06B6D4, #A855F7)',
          backgroundSize: '300% 300%',
          animation: 'gradient-border-spin 6s ease infinite',
        }}
      >
      <div className="bg-slate-900/95 backdrop-blur-2xl rounded-2xl p-8">
        <div className="w-16 h-16 mx-auto rounded-full flex items-center justify-center animate-[pulse-glow_3s_ease-in-out_infinite]">
          <img src="/logo.svg" alt="Abenix" className="w-14 h-14" />
        </div>

        <h2 className="text-xl font-bold text-white text-center mt-4">
          <span
            className={titleDone ? '' : 'border-r-2'}
            style={!titleDone ? { animation: 'typing-cursor 0.7s step-end infinite' } : undefined}
          >
            {titleText}
          </span>
        </h2>
        <p className="text-sm text-slate-400 text-center mt-1">
          Create your account or sign in
        </p>

        {sessionExpired && (
          <p
            role="status"
            className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200 text-center"
          >
            Your session expired. Sign in again to pick up where you left off.
          </p>
        )}

        <div className="flex mt-6 border-b border-slate-700/50">
          {(['login', 'register'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                setError('');
              }}
              aria-label={t === 'login' ? 'Switch to sign in' : 'Switch to register'}
              aria-pressed={tab === t}
              className={`flex-1 pb-3 text-sm font-medium transition-colors ${
                tab === t
                  ? 'text-white border-b-2 border-cyan-400'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {t === 'login' ? 'Sign in' : 'Create account'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <AnimatePresence mode="wait">
            {tab === 'register' && (
              <motion.div
                key="name-field"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <label htmlFor="auth-full-name" className="block text-xs font-medium text-slate-400 mb-1.5">
                  Full Name
                </label>
                <div className="relative">
                  <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
                  <input
                    id="auth-full-name"
                    type="text"
                    placeholder="Full Name"
                    aria-label="Full name"
                    value={form.full_name}
                    onChange={(e) => updateField('full_name', e.target.value)}
                    required={tab === 'register'}
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition outline-none"
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <div>
            <label htmlFor="auth-email" className="block text-xs font-medium text-slate-400 mb-1.5">
              Email Address
            </label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
              <input
                id="auth-email"
                type="email"
                placeholder="Email Address"
                aria-label="Email address"
                value={form.email}
                onChange={(e) => updateField('email', e.target.value)}
                required
                className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-3 text-white text-sm placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition outline-none"
              />
            </div>
          </div>

          <div>
            <label htmlFor="auth-password" className="block text-xs font-medium text-slate-400 mb-1.5">
              Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" aria-hidden="true" />
              <input
                id="auth-password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Password"
                aria-label="Password"
                aria-describedby={tab === 'register' ? 'password-hint' : undefined}
                value={form.password}
                onChange={(e) => updateField('password', e.target.value)}
                required
                minLength={tab === 'register' ? 8 : undefined}
                className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-10 py-3 text-white text-sm placeholder-slate-500 focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500/50 transition outline-none"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition"
              >
                {showPassword ? (
                  <EyeOff className="w-4 h-4" aria-hidden="true" />
                ) : (
                  <Eye className="w-4 h-4" aria-hidden="true" />
                )}
              </button>
            </div>
            {tab === 'register' && (
              <>
                <p id="password-hint" className="text-xs text-slate-500 mt-1">
                  Min 8 characters
                </p>
                <p className="text-xs text-slate-500 mt-1" data-testid="register-invite-hint">
                  Registering creates a new workspace. To join a team, open the invite link your admin sent you.
                </p>
              </>
            )}
            {/*
              Self-serve password reset isn't wired yet — link to a
              mailto so users have a clear next step instead of a
              dead end. The href will switch to an /auth/forgot
              flow once that ships. Always rendered (both tabs) so a
              user who got here via the wrong tab can still find help.
            */}
            <div className="mt-2 text-right">
              <a
                href="mailto:support@abenix.dev?subject=Password%20reset"
                className="text-xs text-cyan-400/80 hover:text-cyan-300 transition"
                aria-label="Forgot password? Email support"
              >
                Forgot password?
              </a>
            </div>
          </div>

          {error && (
            <motion.div
              initial={{ opacity: 0, y: -5 }}
              animate={{ opacity: 1, y: 0 }}
              role="alert"
            >
              <p className="text-red-400 text-xs">{error}</p>
              {error.toLowerCase().includes('connection failed') && (
                <p className="text-red-400/60 text-[10px] mt-0.5">
                  Is the API running on localhost:8000?
                </p>
              )}
            </motion.div>
          )}

          <button
            type="submit"
            disabled={loading}
            aria-label={loading ? 'Submitting...' : tab === 'login' ? 'Sign in to your account' : 'Create a new account'}
            data-testid="auth-submit"
            className="w-full bg-gradient-to-r from-cyan-500 to-purple-600 text-white font-semibold py-3 rounded-lg shadow-lg shadow-cyan-500/25 hover:shadow-cyan-500/40 transition-all flex items-center justify-center gap-2 text-sm disabled:opacity-50"
          >
            {loading ? (
              <span className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" aria-hidden="true" />
            ) : tab === 'login' ? (
              <>
                Sign in to your account
                <ArrowRight className="w-4 h-4" aria-hidden="true" />
              </>
            ) : (
              <>
                Create Account
                <Sparkles className="w-4 h-4" aria-hidden="true" />
              </>
            )}
          </button>
        </form>

        {ssoProviders.length > 0 && (
          <div className="mt-4">
            <div className="relative my-3 text-center">
              <span className="px-2 bg-slate-900 text-[10px] text-slate-500 uppercase tracking-wider relative z-10">
                Or continue with
              </span>
              <span className="absolute left-0 right-0 top-1/2 h-px bg-slate-800" aria-hidden="true" />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {ssoProviders.includes('google') && (
                <a
                  href={`${API_URL}/api/auth/oidc/google/start?return_to=${encodeURIComponent(returnTo)}`}
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-200 hover:border-slate-500 hover:bg-slate-800 transition"
                  aria-label="Sign in with Google"
                >
                  <span aria-hidden="true">G</span> Google
                </a>
              )}
              {ssoProviders.includes('github') && (
                <a
                  href={`${API_URL}/api/auth/oidc/github/start?return_to=${encodeURIComponent(returnTo)}`}
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-200 hover:border-slate-500 hover:bg-slate-800 transition"
                  aria-label="Sign in with GitHub"
                >
                  <span aria-hidden="true"></span> GitHub
                </a>
              )}
              {ssoProviders.includes('microsoft') && (
                <a
                  href={`${API_URL}/api/auth/oidc/microsoft/start?return_to=${encodeURIComponent(returnTo)}`}
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-slate-700 bg-slate-800/40 text-xs text-slate-200 hover:border-slate-500 hover:bg-slate-800 transition"
                  aria-label="Sign in with Microsoft"
                >
                  <span aria-hidden="true">M</span> Microsoft
                </a>
              )}
            </div>
          </div>
        )}

        <div className="mt-4 text-center">
          <p className="text-slate-500 text-xs mb-2">Quick Access:</p>
          <div className="flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={() => submitLogin('admin@abenix.dev', 'Admin123456')}
              disabled={loading}
              aria-label="Sign in as admin demo user"
              className="px-3 py-1.5 text-xs font-medium rounded-md border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 hover:border-cyan-500/50 transition-all disabled:opacity-50"
            >
              Admin Demo
            </button>
            <button
              type="button"
              onClick={() => submitLogin('demo@abenix.dev', 'Demo123456')}
              disabled={loading}
              aria-label="Sign in as regular demo user"
              className="px-3 py-1.5 text-xs font-medium rounded-md border border-purple-500/30 text-purple-400 hover:bg-purple-500/10 hover:border-purple-500/50 transition-all disabled:opacity-50"
            >
              User Demo
            </button>
          </div>
        </div>

        <div className="flex items-center justify-center gap-4 mt-6 pt-4 border-t border-slate-800/50">
          <span className="flex items-center gap-1 text-slate-600 text-xs">
            <Shield className="w-3 h-3" aria-hidden="true" />
            256-bit Encryption
          </span>
          <span className="flex items-center gap-1 text-slate-600 text-xs">
            <Lock className="w-3 h-3" aria-hidden="true" />
            JWT Auth
          </span>
          <span className="flex items-center gap-1 text-slate-600 text-xs">
            <Users className="w-3 h-3" aria-hidden="true" />
            RBAC Enabled
          </span>
        </div>
      </div>
      </div>
    </motion.div>
  );
}
