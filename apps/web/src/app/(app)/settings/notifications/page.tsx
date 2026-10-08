'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Bell, Check, Clock, Hash, Loader2, Mail } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastError, toastSuccess } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';

interface TenantSettings {
  tenant_id: string;
  name: string;
  slug: string;
  slack_webhook_url: string;
  slack_webhook_is_set: boolean;
}

type PrefKey = 'execution_complete' | 'execution_failed' | 'billing_alerts' | 'team_updates' | 'autonomy_updates' | 'moderation_reviews';

interface NotifPrefs extends Record<PrefKey, boolean> {
  channels: { slack: boolean; email: boolean };
  delivery: { slack_available: boolean; email_available: boolean };
}

const PREF_LABELS: { key: PrefKey; label: string; description: string }[] = [
  {
    key: 'execution_complete',
    label: 'Run finished',
    description: 'An agent or pipeline run you started finished successfully.',
  },
  {
    key: 'execution_failed',
    label: 'Run failed',
    description: 'A run you started, or one of your triggers, failed or was stopped as stuck.',
  },
  {
    key: 'team_updates',
    label: 'Sharing and comments',
    description: 'Someone shared something with you, stopped sharing it, commented on or changed your agent, or subscribed to your marketplace listing.',
  },
  {
    key: 'autonomy_updates',
    label: 'Agent autonomy',
    description: 'An agent is ready to move up a level, was moved down after a harm flag or a drop in accuracy, or proposed an action waiting for your review.',
  },
  {
    key: 'moderation_reviews',
    label: 'Content held for review',
    description: 'A moderation policy held a message or a reply and you can review it. Only people with the Review held content permission get these.',
  },
  {
    key: 'billing_alerts',
    label: 'Usage limit warnings',
    description: 'Your workspace has used 80% or more of its daily run limit.',
  },
];

const COMING_SOON = [
  { label: 'Weekly report', description: 'A weekly summary of usage and costs.' },
  { label: 'Product news', description: 'Announcements about new features.' },
];

function Switch({
  id,
  checked,
  disabled,
  onChange,
  labelledBy,
  describedBy,
}: {
  id: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  labelledBy: string;
  describedBy?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      data-testid={id}
      className={`relative w-11 h-6 shrink-0 rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-40 disabled:cursor-not-allowed ${
        checked ? 'bg-cyan-500' : 'bg-slate-700'
      }`}
    >
      <span
        aria-hidden="true"
        className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  );
}

export default function NotificationsPage() {
  usePageTitle('Notifications');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const { data: prefsData, isLoading: loading, error: loadError, mutate } =
    useApi<NotifPrefs>('/api/settings/notifications');
  const { data: tenantData, mutate: mutateTenant } = useApi<TenantSettings>('/api/settings/tenant');
  const [prefs, setPrefs] = useState<NotifPrefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const [slackUrl, setSlackUrl] = useState('');
  const [slackSaving, setSlackSaving] = useState(false);
  const [slackSaved, setSlackSaved] = useState(false);
  const [slackErr, setSlackErr] = useState<string | null>(null);
  const [slackTesting, setSlackTesting] = useState(false);
  const [slackTestResult, setSlackTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (prefsData) setPrefs(prefsData);
  }, [prefsData]);

  useEffect(() => {
    if (tenantData) setSlackUrl(tenantData.slack_webhook_url || '');
  }, [tenantData]);

  const dirty =
    !!prefs &&
    !!prefsData &&
    (PREF_LABELS.some((p) => prefs[p.key] !== prefsData[p.key]) ||
      prefs.channels.slack !== prefsData.channels.slack ||
      prefs.channels.email !== prefsData.channels.email);

  const saveSlack = async () => {
    setSlackErr(null);
    const v = slackUrl.trim();
    if (v && !v.includes('…') && !/^https:\/\/\S+$/i.test(v)) {
      setSlackErr('Paste the full Slack webhook link. It starts with https://hooks.slack.com/');
      return;
    }
    setSlackSaving(true);
    try {
      const r = await apiFetch<TenantSettings>('/api/settings/tenant', {
        method: 'PUT',
        body: JSON.stringify({ slack_webhook_url: v }),
      });
      if (r.data) setSlackUrl(r.data.slack_webhook_url || '');
      mutateTenant();
      mutate();
      setSlackSaved(true);
      setTimeout(() => setSlackSaved(false), 2500);
    } catch (e: unknown) {
      setSlackErr(e instanceof Error ? e.message : 'Could not save the webhook. Try again.');
    }
    setSlackSaving(false);
  };

  const testSlack = async () => {
    setSlackTesting(true);
    setSlackTestResult(null);
    setSlackErr(null);
    try {
      const r = await apiFetch<{ channel: string; delivered: boolean }>(
        '/api/admin/notification-channels/slack/test',
        { method: 'POST' },
      );
      setSlackTestResult(
        r.data?.delivered
          ? { ok: true, text: 'Sent. Check your Slack channel.' }
          : { ok: false, text: 'Slack did not accept the message. Check the webhook link.' },
      );
      setTimeout(() => setSlackTestResult(null), 6000);
    } catch (e: unknown) {
      setSlackErr(e instanceof Error ? e.message : 'The test could not be sent.');
    }
    setSlackTesting(false);
  };

  const setPref = (key: PrefKey, v: boolean) => prefs && setPrefs({ ...prefs, [key]: v });
  const setChannel = (ch: 'slack' | 'email', v: boolean) =>
    prefs && setPrefs({ ...prefs, channels: { ...prefs.channels, [ch]: v } });

  const handleSave = async () => {
    if (!prefs) return;
    setSaving(true);
    try {
      const body = {
        ...Object.fromEntries(PREF_LABELS.map((p) => [p.key, prefs[p.key]])),
        channels: prefs.channels,
      };
      const r = await apiFetch<NotifPrefs>('/api/settings/notifications', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      if (r.data) setPrefs(r.data);
      mutate();
      setSaved(true);
      toastSuccess('Notification preferences saved');
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      toastError(e instanceof Error ? e.message : 'Could not save your preferences. Try again.');
    } finally {
      setSaving(false);
    }
  };

  if (loading && !prefs) {
    return (
      <div className="flex items-center justify-center py-20" aria-busy="true">
        <div className="w-8 h-8 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!prefs) {
    return (
      <div className="max-w-2xl rounded-xl border border-rose-500/30 bg-rose-500/5 p-6" role="alert">
        <p className="text-sm text-rose-200">Your notification preferences could not be loaded.</p>
        {loadError && <p className="text-xs text-slate-400 mt-1">{loadError}</p>}
        <button type="button" onClick={() => mutate()} className="mt-3 text-sm text-cyan-300 hover:underline">
          Try again
        </button>
      </div>
    );
  }

  const slackSet = !!tenantData?.slack_webhook_is_set;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <PageHeader
        title="Notifications"
        icon={Bell}
        purpose="Choose which events reach your notification bell, and whether copies also go to Slack or email. For everyone."
        primaryAction={{
          label: 'Save preferences',
          icon: saving ? Loader2 : Check,
          busy: saving,
          disabled: !dirty,
          title: dirty ? undefined : 'Change a switch first',
          onClick: handleSave,
          testId: 'notif-save',
        }}
        steps={[
          'Turn on the events you want to hear about. They land in the bell at the top.',
          'Pick whether copies also go to the workspace Slack channel or to your email.',
          'Press Save preferences. Approvals and platform alerts always reach you.',
          'An admin connects the Slack channel at the bottom of this page.',
        ]}
        docSlug="06-deployment/04-observability"
        storageKey="settings-notifications"
      />

      <section aria-labelledby="notif-events-title" className="space-y-2">
        <h2 id="notif-events-title" className="text-sm font-semibold text-white">What to tell you about</h2>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          {PREF_LABELS.map((item, i) => (
            <div
              key={item.key}
              className={`flex items-center justify-between gap-4 p-4 ${
                i < PREF_LABELS.length - 1 ? 'border-b border-slate-700/30' : ''
              }`}
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="hidden sm:flex w-9 h-9 rounded-lg bg-slate-700/30 items-center justify-center shrink-0">
                  <Bell className="w-4 h-4 text-slate-400" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                  <p id={`pref-${item.key}-label`} className="text-sm font-medium text-white">{item.label}</p>
                  <p id={`pref-${item.key}-desc`} className="text-xs text-slate-500">{item.description}</p>
                </div>
              </div>
              <Switch
                id={`pref-${item.key}`}
                checked={prefs[item.key]}
                onChange={(v) => setPref(item.key, v)}
                labelledBy={`pref-${item.key}-label`}
                describedBy={`pref-${item.key}-desc`}
              />
            </div>
          ))}
        </div>
        <p className="text-xs text-slate-500">
          Approval requests and platform alerts always reach you, because they need someone to act.
        </p>
      </section>

      <section aria-labelledby="notif-channels-title" className="space-y-2">
        <h2 id="notif-channels-title" className="text-sm font-semibold text-white">Where else to send them</h2>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between gap-4 p-4 border-b border-slate-700/30">
            <div className="flex items-center gap-3 min-w-0">
              <div className="hidden sm:flex w-9 h-9 rounded-lg bg-slate-700/30 items-center justify-center shrink-0">
                <Hash className="w-4 h-4 text-slate-400" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <p id="chan-slack-label" className="text-sm font-medium text-white">Copy to the workspace Slack channel</p>
                <p id="chan-slack-desc" className="text-xs text-slate-500">
                  {prefs.delivery.slack_available
                    ? 'Your notifications are also posted to the Slack channel set below.'
                    : 'Not available yet. No Slack channel is connected for this workspace.'}
                </p>
              </div>
            </div>
            <Switch
              id="chan-slack"
              checked={prefs.delivery.slack_available && prefs.channels.slack}
              disabled={!prefs.delivery.slack_available}
              onChange={(v) => setChannel('slack', v)}
              labelledBy="chan-slack-label"
              describedBy="chan-slack-desc"
            />
          </div>
          <div className="flex items-center justify-between gap-4 p-4">
            <div className="flex items-center gap-3 min-w-0">
              <div className="hidden sm:flex w-9 h-9 rounded-lg bg-slate-700/30 items-center justify-center shrink-0">
                <Mail className="w-4 h-4 text-slate-400" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <p id="chan-email-label" className="text-sm font-medium text-white">Email me about failures and alerts</p>
                <p id="chan-email-desc" className="text-xs text-slate-500">
                  {prefs.delivery.email_available
                    ? `Failed runs and alerts are also emailed to ${user?.email || 'you'}. Successful runs are not emailed.`
                    : 'Not available. Outgoing email is not set up on this platform. An operator can enable it.'}
                </p>
              </div>
            </div>
            <Switch
              id="chan-email"
              checked={prefs.delivery.email_available && prefs.channels.email}
              disabled={!prefs.delivery.email_available}
              onChange={(v) => setChannel('email', v)}
              labelledBy="chan-email-label"
              describedBy="chan-email-desc"
            />
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-3">
        {saved ? (
          <span className="text-xs text-emerald-400 flex items-center gap-1" role="status">
            <Check className="w-3 h-3" />
            Preferences saved
          </span>
        ) : dirty ? (
          <span className="text-xs text-amber-300">You have unsaved changes. Press Save preferences at the top.</span>
        ) : null}
      </div>

      <section aria-labelledby="notif-soon-title" className="space-y-2">
        <h2 id="notif-soon-title" className="text-sm font-semibold text-slate-400">Coming soon</h2>
        <ul className="rounded-xl border border-dashed border-slate-700/60 divide-y divide-slate-800">
          {COMING_SOON.map((c) => (
            <li key={c.label} className="flex items-center gap-3 p-3">
              <Clock className="w-4 h-4 text-slate-600 shrink-0" aria-hidden="true" />
              <div>
                <p className="text-sm text-slate-400">{c.label}</p>
                <p className="text-xs text-slate-600">{c.description} Not sent yet, so there is nothing to turn on.</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="pt-6 border-t border-slate-700/40" data-testid="slack-webhook-section" aria-labelledby="slack-title">
        <h2 id="slack-title" className="text-lg font-semibold text-white">Workspace Slack channel</h2>
        <p className="text-xs text-slate-500 mt-1 mb-3">
          One Slack incoming webhook for the whole workspace. Members who keep the Slack copy turned on get their
          notifications posted there. Leave it blank to stop all Slack posts.{' '}
          {isAdmin ? 'Only admins can change it.' : 'Only an admin can change it.'}
        </p>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 space-y-3">
          <p className="text-xs" data-testid="slack-webhook-source">
            {slackSet ? (
              <span className="text-emerald-300 inline-flex items-center gap-1">
                <Check className="w-3 h-3" /> A Slack channel is connected.
              </span>
            ) : (
              <span className="text-slate-400">No Slack channel is connected yet.</span>
            )}
          </p>
          {isAdmin ? (
            <>
              <label className="block" htmlFor="slack-webhook-input">
                <span className="text-xs text-slate-400 mb-1 flex items-center gap-1.5">
                  <Hash className="w-3 h-3" aria-hidden="true" /> Webhook link
                </span>
              </label>
              <input
                id="slack-webhook-input"
                data-testid="slack-webhook-input"
                value={slackUrl}
                onChange={(e) => {
                  setSlackUrl(e.target.value);
                  setSlackErr(null);
                }}
                placeholder="https://hooks.slack.com/services/T…/B…/…"
                aria-invalid={!!slackErr}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500/50"
              />
              <p className="text-[11px] text-slate-500">
                Create one in Slack under Apps, Incoming Webhooks. For safety only the end of a saved link is shown.
              </p>
              {slackErr && (
                <p className="text-xs text-rose-300 flex items-center gap-1" role="alert" data-testid="slack-webhook-error">
                  <AlertTriangle className="w-3 h-3" /> {slackErr}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <button
                  data-testid="slack-webhook-save"
                  onClick={saveSlack}
                  disabled={slackSaving}
                  className="px-3 py-1.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 text-xs font-medium rounded-lg inline-flex items-center gap-1.5"
                >
                  {slackSaving && <Loader2 className="w-3 h-3 animate-spin" />}
                  Save webhook
                </button>
                <button
                  data-testid="slack-test-send"
                  onClick={testSlack}
                  disabled={slackTesting || !slackSet}
                  title={slackSet ? undefined : 'Save a webhook first'}
                  className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-100 text-xs font-medium rounded-lg inline-flex items-center gap-1.5"
                >
                  {slackTesting && <Loader2 className="w-3 h-3 animate-spin" />}
                  Send test message
                </button>
                {slackSaved && (
                  <span className="text-xs text-emerald-400 flex items-center gap-1" role="status">
                    <Check className="w-3 h-3" /> Saved
                  </span>
                )}
                {slackTestResult && (
                  <span className={`text-xs ${slackTestResult.ok ? 'text-cyan-300' : 'text-rose-300'}`} role="status">
                    {slackTestResult.text}
                  </span>
                )}
              </div>
            </>
          ) : null}
        </div>
      </section>
    </motion.div>
  );
}
