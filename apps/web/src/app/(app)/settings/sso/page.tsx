'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Building2, Check, Copy, Loader2, PlugZap, Save, Trash2 } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';

interface SsoConfig {
  configured: boolean;
  enabled: boolean;
  issuer: string;
  client_id: string;
  client_secret_set: boolean;
  domains: string[];
  default_role: string;
  label: string;
  auto_create: boolean;
  redirect_uri: string;
  start_url: string;
}

const ROLES = [
  { value: 'user', label: 'User', hint: 'Runs agents shared with them' },
  { value: 'creator', label: 'Creator', hint: 'Also builds agents and pipelines' },
  { value: 'admin', label: 'Admin', hint: 'Also manages the workspace' },
];

const inputCls =
  'w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50 aria-[invalid=true]:border-rose-500/60';

function errText(e: unknown, fallback: string) {
  return e instanceof Error && e.message ? e.message : fallback;
}

export default function SsoSettingsPage() {
  usePageTitle('Single sign-on');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const { data, isLoading, error: loadError, mutate } = useApi<SsoConfig>(isAdmin ? '/api/settings/sso' : null);

  const [issuer, setIssuer] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [domains, setDomains] = useState('');
  const [role, setRole] = useState('user');
  const [label, setLabel] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [autoCreate, setAutoCreate] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [err, setErr] = useState('');
  const [testMsg, setTestMsg] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!data) return;
    setIssuer(data.issuer);
    setClientId(data.client_id);
    setDomains(data.domains.join(', '));
    setRole(data.default_role);
    setLabel(data.label);
    setEnabled(data.configured ? data.enabled : true);
    setAutoCreate(data.auto_create);
  }, [data]);

  const body = () => ({
    enabled,
    issuer: issuer.trim(),
    client_id: clientId.trim(),
    client_secret: clientSecret.trim() || null,
    domains: domains.split(/[\s,;]+/).map((d) => d.trim()).filter(Boolean),
    default_role: role,
    label: label.trim(),
    auto_create: autoCreate,
  });

  const issuerBad = issuer.trim() !== '' && !/^https?:\/\/\S+$/i.test(issuer.trim());
  const missing = !issuer.trim() || !clientId.trim() || (!data?.client_secret_set && !clientSecret.trim()) || (enabled && !domains.trim());

  const save = async () => {
    setErr('');
    setTestMsg('');
    setSaving(true);
    try {
      await apiFetch('/api/settings/sso', { method: 'PUT', body: JSON.stringify(body()) });
      setClientSecret('');
      mutate();
      toastSuccess('Single sign-on saved');
    } catch (e) {
      setErr(errText(e, 'Could not save. Try again.'));
    }
    setSaving(false);
  };

  const test = async () => {
    setErr('');
    setTestMsg('');
    setTesting(true);
    try {
      const r = await apiFetch<{ authorization_endpoint: string }>('/api/settings/sso/test', {
        method: 'POST',
        body: JSON.stringify(body()),
      });
      setTestMsg(`The provider answered. People will sign in at ${r.data?.authorization_endpoint}`);
    } catch (e) {
      setErr(errText(e, 'The provider did not answer.'));
    }
    setTesting(false);
  };

  const remove = async () => {
    if (!window.confirm('Remove single sign-on? People who only sign in with it will need Forgot password to get back in.')) return;
    setErr('');
    try {
      await apiFetch('/api/settings/sso', { method: 'DELETE' });
      setClientSecret('');
      mutate();
      toastSuccess('Single sign-on removed');
    } catch (e) {
      setErr(errText(e, 'Could not remove it.'));
    }
  };

  const copyRedirect = async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.redirect_uri);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };

  if (!isAdmin) {
    return (
      <div className="max-w-2xl rounded-xl border border-slate-700/50 bg-slate-800/30 p-6" role="status">
        <p className="text-sm text-slate-200">Only workspace admins can set up single sign-on.</p>
        <p className="text-xs text-slate-500 mt-1">Ask an admin if your company wants people to sign in with their work account.</p>
      </div>
    );
  }

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center py-20" aria-busy="true">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="max-w-2xl rounded-xl border border-rose-500/30 bg-rose-500/5 p-6" role="alert">
        <p className="text-sm text-rose-200">Single sign-on settings could not be loaded.</p>
        {loadError && <p className="text-xs text-slate-400 mt-1">{String(loadError)}</p>}
        <button type="button" onClick={() => mutate()} className="mt-3 text-sm text-cyan-300 hover:underline">Try again</button>
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="space-y-6 max-w-2xl" data-testid="sso-page">
      <PageHeader
        title="Single sign-on"
        icon={Building2}
        purpose="Let people sign in with their company account through any OpenID Connect provider, such as Okta, Entra ID, Google Workspace or Keycloak. For admins."
        steps={[
          'In your provider, create a web app and paste the redirect address below into it.',
          'Copy the issuer, client ID and client secret from the provider into this form.',
          'List the email domains that belong to your company and pick the role new people get.',
          'Press Test connection, then Save. People choose Sign in with your company on the sign-in page.',
        ]}
        docSlug="09-reference/05-sso"
        storageKey="settings-sso"
      />

      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6 space-y-2" aria-labelledby="sso-redirect-title">
        <h2 id="sso-redirect-title" className="text-sm font-semibold text-white">Redirect address for your provider</h2>
        <div className="flex flex-col sm:flex-row gap-2">
          <code data-testid="sso-redirect-uri" className="flex-1 min-w-0 break-all text-xs text-slate-100 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2">
            {data.redirect_uri}
          </code>
          <button type="button" onClick={copyRedirect} className="px-3 py-2 bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs rounded-lg inline-flex items-center justify-center gap-1.5">
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />} {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </section>

      <section className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6 space-y-4" aria-labelledby="sso-form-title">
        <div className="flex items-center gap-2">
          <h2 id="sso-form-title" className="text-sm font-semibold text-white">Provider</h2>
          <span data-testid="sso-status" className={`ml-auto text-[11px] px-2 py-0.5 rounded border ${data.configured && data.enabled ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30' : 'text-slate-400 bg-slate-700/30 border-slate-600/40'}`}>
            {!data.configured ? 'Not set up' : data.enabled ? 'On' : 'Saved, turned off'}
          </span>
        </div>

        <div>
          <label htmlFor="sso-issuer" className="block text-xs text-slate-400 mb-1">Issuer URL</label>
          <input id="sso-issuer" value={issuer} onChange={(e) => { setIssuer(e.target.value); setErr(''); }} placeholder="https://login.example.com" aria-invalid={issuerBad} className={inputCls} />
          <p className="text-[11px] mt-1 text-slate-500">{issuerBad ? 'Use the full address, starting with https://' : 'The provider serves /.well-known/openid-configuration under it.'}</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="sso-client-id" className="block text-xs text-slate-400 mb-1">Client ID</label>
            <input id="sso-client-id" value={clientId} onChange={(e) => { setClientId(e.target.value); setErr(''); }} className={inputCls} />
          </div>
          <div>
            <label htmlFor="sso-client-secret" className="block text-xs text-slate-400 mb-1">Client secret</label>
            <input id="sso-client-secret" type="password" autoComplete="off" value={clientSecret} onChange={(e) => { setClientSecret(e.target.value); setErr(''); }} placeholder={data.client_secret_set ? 'Saved. Type to replace it' : ''} className={inputCls} />
          </div>
        </div>
        <div>
          <label htmlFor="sso-domains" className="block text-xs text-slate-400 mb-1">Email domains</label>
          <input id="sso-domains" value={domains} onChange={(e) => { setDomains(e.target.value); setErr(''); }} placeholder="example.com, example.co.uk" className={inputCls} />
          <p className="text-[11px] mt-1 text-slate-500">People whose email ends in one of these are sent to your provider. Separate with commas.</p>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="sso-role" className="block text-xs text-slate-400 mb-1">Role for new people</label>
            <select id="sso-role" value={role} onChange={(e) => setRole(e.target.value)} className={inputCls}>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}. {r.hint}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="sso-label" className="block text-xs text-slate-400 mb-1">Name on the sign-in page (optional)</label>
            <input id="sso-label" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Acme login" maxLength={60} className={inputCls} />
          </div>
        </div>
        <label className="flex items-start gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={autoCreate} onChange={(e) => setAutoCreate(e.target.checked)} className="mt-0.5" data-testid="sso-auto-create" />
          <span>Create an account the first time someone from these domains signs in. Turn off to allow invited people only.</span>
        </label>
        <label className="flex items-start gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="mt-0.5" data-testid="sso-enabled" />
          <span>Single sign-on is on</span>
        </label>

        {err && (
          <p role="alert" data-testid="sso-error" className="text-xs text-rose-300 flex items-start gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" /> {err}
          </p>
        )}
        {testMsg && <p role="status" data-testid="sso-test-result" className="text-xs text-emerald-300 break-all">{testMsg}</p>}

        <div className="flex flex-wrap gap-2 pt-1">
          <button type="button" onClick={test} disabled={testing || !issuer.trim() || issuerBad} data-testid="sso-test" className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-100 text-xs font-medium rounded-lg inline-flex items-center gap-1.5">
            {testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <PlugZap className="w-3 h-3" />} Test connection
          </button>
          <button type="button" onClick={save} disabled={saving || missing || issuerBad} title={missing ? 'Fill in the issuer, client ID, secret and domains first' : undefined} data-testid="sso-save" className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 text-xs font-medium rounded-lg inline-flex items-center gap-1.5">
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Save
          </button>
          {data.configured && (
            <button type="button" onClick={remove} data-testid="sso-remove" className="ml-auto px-3 py-1.5 border border-slate-600 hover:border-rose-500/60 text-slate-300 text-xs rounded-lg inline-flex items-center gap-1.5">
              <Trash2 className="w-3 h-3" /> Remove
            </button>
          )}
        </div>
      </section>
    </motion.div>
  );
}
