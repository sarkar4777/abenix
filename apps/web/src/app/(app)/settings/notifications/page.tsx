'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Bell, Check, Loader2, Hash, AlertTriangle } from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';

interface TenantSettings {
  tenant_id: string;
  name: string;
  slug: string;
  slack_webhook_url: string;
  slack_webhook_url_source: 'tenant' | 'env_fallback';
}

interface NotifPrefs {
  execution_complete: boolean;
  execution_failed: boolean;
  weekly_report: boolean;
  billing_alerts: boolean;
  team_updates: boolean;
  marketing: boolean;
}

const PREF_LABELS: { key: keyof NotifPrefs; label: string; description: string }[] = [
  {
    key: 'execution_complete',
    label: 'Execution Complete',
    description: 'Get notified when agent executions finish successfully',
  },
  {
    key: 'execution_failed',
    label: 'Execution Failed',
    description: 'Get notified when agent executions fail',
  },
  {
    key: 'weekly_report',
    label: 'Weekly Report',
    description: 'Receive a weekly summary of usage and costs',
  },
  {
    key: 'billing_alerts',
    label: 'Billing Alerts',
    description: 'Get notified about billing events and plan limit warnings',
  },
  {
    key: 'team_updates',
    label: 'Team Updates',
    description: 'Get notified when team members join or leave',
  },
  {
    key: 'marketing',
    label: 'Product Updates',
    description: 'Receive news about new features and improvements',
  },
];

export default function NotificationsPage() {
  usePageTitle('Notifications');
  const { data: prefsData, isLoading: loading } =
    useApi<NotifPrefs>('/api/settings/notifications');
  const { data: tenantData } = useApi<TenantSettings>('/api/settings/tenant');
  const [prefs, setPrefs] = useState<NotifPrefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Tenant Slack webhook
  const [slackUrl, setSlackUrl] = useState('');
  const [slackSource, setSlackSource] = useState<'tenant' | 'env_fallback'>('env_fallback');
  const [slackSaving, setSlackSaving] = useState(false);
  const [slackSaved, setSlackSaved] = useState(false);
  const [slackErr, setSlackErr] = useState<string | null>(null);

  useEffect(() => {
    if (prefsData) setPrefs(prefsData);
  }, [prefsData]);

  useEffect(() => {
    if (tenantData) {
      setSlackUrl(tenantData.slack_webhook_url || '');
      setSlackSource(tenantData.slack_webhook_url_source);
    }
  }, [tenantData]);

  const saveSlack = async () => {
    setSlackSaving(true); setSlackErr(null);
    try {
      const r = await apiFetch<TenantSettings>('/api/settings/tenant', {
        method: 'PUT',
        body: JSON.stringify({ slack_webhook_url: slackUrl }),
      });
      const d = r.data;
      if (d) {
        setSlackUrl(d.slack_webhook_url || '');
        setSlackSource(d.slack_webhook_url_source);
      }
      setSlackSaved(true);
      setTimeout(() => setSlackSaved(false), 2500);
    } catch (e: unknown) {
      setSlackErr(e instanceof Error ? e.message : 'Save failed');
    }
    setSlackSaving(false);
  };

  const handleToggle = (key: keyof NotifPrefs) => {
    if (!prefs) return;
    setPrefs({ ...prefs, [key]: !prefs[key] });
  };

  const handleSave = async () => {
    if (!prefs) return;
    setSaving(true);
    try {
      await apiFetch('/api/settings/notifications', {
        method: 'PUT',
        body: JSON.stringify(prefs),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      // skip
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <div>
        <h1 className="text-2xl font-bold text-white">Notifications</h1>
        <p className="text-sm text-slate-500 mt-1">
          Choose what email notifications you receive
        </p>
      </div>

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
        {PREF_LABELS.map((item, i) => (
          <div
            key={item.key}
            className={`flex items-center justify-between p-4 ${
              i < PREF_LABELS.length - 1 ? 'border-b border-slate-700/30' : ''
            }`}
          >
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-slate-700/30 flex items-center justify-center shrink-0">
                <Bell className="w-4 h-4 text-slate-400" />
              </div>
              <div>
                <p className="text-sm font-medium text-white">{item.label}</p>
                <p className="text-xs text-slate-500">{item.description}</p>
              </div>
            </div>
            <button
              onClick={() => handleToggle(item.key)}
              className={`relative w-11 h-6 rounded-full transition-colors ${
                prefs?.[item.key]
                  ? 'bg-cyan-500'
                  : 'bg-slate-700'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                  prefs?.[item.key] ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between">
        {saved && (
          <span className="text-xs text-emerald-400 flex items-center gap-1">
            <Check className="w-3 h-3" />
            Preferences saved
          </span>
        )}
        <div className="ml-auto">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all disabled:opacity-50 flex items-center gap-2"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save Preferences
          </button>
        </div>
      </div>

      {/* ── Tenant Slack webhook ──────────────────────────────────── */}
      <div className="pt-6 border-t border-slate-700/40" data-testid="slack-webhook-section">
        <h2 className="text-lg font-semibold text-white">Slack webhook (tenant-wide)</h2>
        <p className="text-xs text-slate-500 mt-1 mb-3">
          When set, Abenix posts notification messages to this Slack URL for every
          user in your tenant who has Slack enabled. Falls back to the platform-wide env
          var when blank. Admins only.
        </p>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
          <label className="block">
            <span className="text-xs text-slate-400 mb-1 flex items-center gap-1.5">
              <Hash className="w-3 h-3" /> Webhook URL
            </span>
            <input
              data-testid="slack-webhook-input"
              value={slackUrl}
              onChange={(e) => setSlackUrl(e.target.value)}
              placeholder="https://hooks.slack.com/services/T…/B…/…"
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
            />
          </label>
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-500" data-testid="slack-webhook-source">
              source: <b>{slackSource}</b>
            </span>
            <div className="flex items-center gap-3">
              {slackSaved && (
                <span className="text-xs text-emerald-400 flex items-center gap-1">
                  <Check className="w-3 h-3" /> Saved
                </span>
              )}
              {slackErr && (
                <span className="text-xs text-rose-400 flex items-center gap-1" data-testid="slack-webhook-error">
                  <AlertTriangle className="w-3 h-3" /> {slackErr}
                </span>
              )}
              <button
                data-testid="slack-webhook-save"
                onClick={saveSlack}
                disabled={slackSaving}
                className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 text-xs font-medium rounded-lg inline-flex items-center gap-1.5"
              >
                {slackSaving && <Loader2 className="w-3 h-3 animate-spin" />}
                Save webhook
              </button>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
