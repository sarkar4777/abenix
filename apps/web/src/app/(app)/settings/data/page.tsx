'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertCircle, Check, Database, Loader2, Plus, Save, Shield, ShieldAlert, Trash2 } from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { useAuth } from '@/contexts/AuthContext';
import PageHeader from '@/components/layout/PageHeader';
import {
  DLP_MODES,
  RETENTION_FIELDS,
  dlpPatternProblem,
  retentionProblem,
  type DlpMode,
  type RetentionKey,
} from '@/lib/settings-validation';

interface DlpSettings {
  mode: DlpMode;
  enabled: boolean;
  custom_patterns?: Record<string, string>;
}
type Retention = Record<RetentionKey, number>;
interface PatternRow {
  id: number;
  name: string;
  regex: string;
}

const INPUT = 'w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:opacity-60';

let nextRowId = 1;
const toRows = (patterns?: Record<string, string>): PatternRow[] =>
  Object.entries(patterns || {}).map(([name, regex]) => ({ id: nextRowId++, name, regex }));
const toPatterns = (rows: PatternRow[]) => Object.fromEntries(rows.map((r) => [r.name.trim(), r.regex]));
const dlpSnapshot = (enabled: boolean, mode: DlpMode, rows: PatternRow[]) => JSON.stringify({ enabled, mode, custom_patterns: toPatterns(rows) });
const toDays = (r: Retention) => Object.fromEntries(RETENTION_FIELDS.map((f) => [f.key, String(r[f.key])])) as Record<RetentionKey, string>;

export default function DataSettingsPage() {
  usePageTitle('Data & DLP');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [enabled, setEnabled] = useState(false);
  const [mode, setMode] = useState<DlpMode>('detect');
  const [rows, setRows] = useState<PatternRow[]>([]);
  const [days, setDays] = useState<Record<RetentionKey, string> | null>(null);
  const [savedDlp, setSavedDlp] = useState('');
  const [savedDays, setSavedDays] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');

  const applyDlp = (d: DlpSettings) => {
    const nextRows = toRows(d.custom_patterns);
    setEnabled(!!d.enabled);
    setMode(d.mode || 'detect');
    setRows(nextRows);
    setSavedDlp(dlpSnapshot(!!d.enabled, d.mode || 'detect', nextRows));
  };
  const applyRetention = (r: Retention) => {
    const next = toDays(r);
    setDays(next);
    setSavedDays(JSON.stringify(next));
  };

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    const [dlp, retention] = await Promise.all([
      apiFetch<DlpSettings>('/api/settings/dlp', { throwOnError: false, silent: true }),
      apiFetch<Retention>('/api/settings/retention', { throwOnError: false, silent: true }),
    ]);
    if (dlp.data && retention.data) {
      applyDlp(dlp.data);
      applyRetention(retention.data);
    } else {
      setLoadError(dlp.error || retention.error || 'These settings could not be loaded.');
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const changed = () => {
    setSaved(false);
    setSaveError('');
  };
  const editRow = (id: number, patch: Partial<PatternRow>) => {
    changed();
    setRows((all) => all.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const rowProblem = (r: PatternRow) => dlpPatternProblem(r.name, r.regex, rows.filter((o) => o.id !== r.id).map((o) => o.name));
  const dayProblem = (key: RetentionKey, min: number) => (days ? retentionProblem(days[key], min) : null);
  const invalid = rows.some((r) => !!rowProblem(r)) || RETENTION_FIELDS.some((f) => !!dayProblem(f.key, f.min));
  const canSave = isAdmin && !!days && !invalid && !saving;

  const save = async () => {
    if (!canSave || !days) return;
    setSaving(true);
    changed();
    const problems: string[] = [];
    if (dlpSnapshot(enabled, mode, rows) !== savedDlp) {
      const res = await apiFetch<DlpSettings>('/api/settings/dlp', {
        method: 'PUT',
        body: JSON.stringify({ enabled, mode, custom_patterns: toPatterns(rows) }),
        throwOnError: false,
        silent: true,
      });
      if (res.data) applyDlp(res.data);
      else problems.push(`DLP was not saved. ${res.error || 'Try again.'}`);
    }
    if (JSON.stringify(days) !== savedDays) {
      const body = Object.fromEntries(RETENTION_FIELDS.map((f) => [f.key, parseInt(days[f.key], 10)]));
      const res = await apiFetch<Retention>('/api/settings/retention', {
        method: 'PUT',
        body: JSON.stringify(body),
        throwOnError: false,
        silent: true,
      });
      if (res.data) applyRetention(res.data);
      else problems.push(`Retention was not saved. ${res.error || 'Try again.'}`);
    }
    setSaving(false);
    if (problems.length) setSaveError(problems.join(' '));
    else setSaved(true);
  };

  const disabledReason = !isAdmin ? 'Only a workspace admin can change these settings' : invalid ? 'Fix the highlighted values first' : undefined;

  const status = (testId?: string) => (
    <>
      {saved && (
        <p role="status" data-testid={testId ? `${testId}-saved` : undefined} className="flex items-center gap-1.5 text-sm text-emerald-300">
          <Check className="h-4 w-4" /> Saved
        </p>
      )}
      {saveError && (
        <p role="alert" data-testid={testId ? `${testId}-error` : undefined} className="flex items-start gap-1.5 text-sm text-rose-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> {saveError}
        </p>
      )}
    </>
  );

  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader
        title="Data & DLP"
        icon={Shield}
        purpose={isAdmin
          ? 'Protect personal data in agent messages and answers, and set how long this workspace keeps its history. For workspace admins.'
          : 'How this workspace protects personal data in agent messages and answers, and how long it keeps its history. An admin changes these.'}
        primaryAction={{
          label: saving ? 'Saving' : 'Save changes',
          icon: saving ? Loader2 : Save,
          onClick: save,
          disabled: !canSave,
          busy: saving,
          title: disabledReason,
          testId: 'data-settings-save',
        }}
        secondaryAction={{ label: 'Open Moderation', icon: ShieldAlert, href: '/moderation' }}
        steps={isAdmin ? [
          'Turn on DLP to scan every message sent to an agent and every answer it gives.',
          'Pick what happens when personal data is found. Detect logs it, Mask replaces it and Block refuses it.',
          'Add your own patterns for things like order or customer numbers.',
          'Set how long history is kept and press Save changes. A new DLP mode applies to the next run.',
        ] : [
          'When DLP is on, every message to an agent and every answer it gives is scanned.',
          'Detect logs personal data, Mask replaces it and Block refuses it.',
          'Ask a workspace admin if these settings need to change.',
        ]}
        docSlug="02-runtime/13-moderation-gate"
        storageKey="settings-data"
      />

      {user && !isAdmin && (
        <p role="status" data-testid="data-settings-readonly" className="rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-2 text-xs text-slate-300">
          View only. Only a workspace admin can change these settings.
        </p>
      )}

      {status('data-settings')}

      {loading && !days && (
        <div className="flex items-center justify-center py-16 text-sm text-slate-400">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-cyan-500" /> Loading settings
        </div>
      )}

      {loadError && (
        <div role="alert" data-testid="data-settings-load-error" className="rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-sm text-rose-200">
          {loadError}{' '}
          <button type="button" onClick={load} className="text-cyan-300 hover:underline">Try again</button>
        </div>
      )}

      {days && (
        <>
          <section className="space-y-4 rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" aria-labelledby="dlp-title">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="dlp-title" className="text-sm font-semibold text-white">DLP and personal data protection</h2>
                <p className="mt-1 text-xs text-slate-400">
                  Scans for email addresses, US phone numbers, SSNs, card numbers, IP addresses, cloud keys, API keys and bearer tokens.
                  It covers agents and pipelines on every way of running them.
                </p>
              </div>
              <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm text-slate-200">
                <input
                  type="checkbox"
                  checked={enabled}
                  disabled={!isAdmin}
                  onChange={(e) => { changed(); setEnabled(e.target.checked); }}
                  data-testid="dlp-enabled"
                  className="h-4 w-4 accent-cyan-500 disabled:cursor-not-allowed"
                />
                {enabled ? 'On' : 'Off'}
              </label>
            </div>

            <div>
              <label htmlFor="dlp-mode" className="mb-1 block text-xs font-medium text-slate-300">When personal data is found</label>
              <select
                id="dlp-mode"
                value={mode}
                disabled={!isAdmin}
                onChange={(e) => { changed(); setMode(e.target.value as DlpMode); }}
                data-testid="dlp-mode"
                className={`${INPUT} border-slate-600 sm:max-w-xs`}
              >
                {DLP_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              <p data-testid="dlp-mode-help" className="mt-1.5 text-xs text-slate-400">
                {DLP_MODES.find((m) => m.value === mode)?.help}
                {!enabled && ' DLP is off, so nothing is scanned until you turn it on.'}
              </p>
            </div>

            <div className="border-t border-slate-700/50 pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="text-xs font-medium text-slate-300">Your own patterns</h3>
                  <p className="mt-0.5 text-xs text-slate-500">Each one is a regular expression. A match follows the mode above.</p>
                </div>
                {isAdmin && (
                  <button
                    type="button"
                    onClick={() => { changed(); setRows((all) => [...all, { id: nextRowId++, name: '', regex: '' }]); }}
                    data-testid="dlp-pattern-add"
                    className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
                  >
                    <Plus className="h-3.5 w-3.5" /> Add a pattern
                  </button>
                )}
              </div>
              {rows.length === 0 && <p className="mt-2 text-xs text-slate-500">No patterns of your own yet.</p>}
              <ul className="mt-2 space-y-2">
                {rows.map((r) => {
                  const problem = rowProblem(r);
                  return (
                    <li key={r.id} data-testid="dlp-pattern-row">
                      <div className="flex flex-col gap-2 sm:flex-row">
                        <input
                          value={r.name}
                          disabled={!isAdmin}
                          onChange={(e) => editRow(r.id, { name: e.target.value })}
                          placeholder="Name, such as order"
                          aria-label="Pattern name"
                          data-testid="dlp-pattern-name"
                          className={`${INPUT} border-slate-600 sm:w-44`}
                        />
                        <input
                          value={r.regex}
                          disabled={!isAdmin}
                          onChange={(e) => editRow(r.id, { regex: e.target.value })}
                          placeholder="ORD-\d+"
                          aria-label={`Regular expression for ${r.name || 'this pattern'}`}
                          aria-invalid={!!problem}
                          spellCheck={false}
                          data-testid="dlp-pattern-regex"
                          className={`${INPUT} min-w-0 flex-1 font-mono ${problem ? 'border-rose-500/70' : 'border-slate-600'}`}
                        />
                        {isAdmin && (
                          <button
                            type="button"
                            onClick={() => { changed(); setRows((all) => all.filter((o) => o.id !== r.id)); }}
                            aria-label={`Remove ${r.name || 'this pattern'}`}
                            data-testid="dlp-pattern-remove"
                            className="inline-flex min-h-[36px] items-center justify-center rounded-lg border border-slate-700 px-3 text-slate-400 hover:text-rose-300"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                      {problem && <p className="mt-1 text-xs text-rose-300">{problem}</p>}
                    </li>
                  );
                })}
              </ul>
            </div>
          </section>

          <section className="space-y-4 rounded-xl border border-slate-700/50 bg-slate-800/30 p-5" aria-labelledby="retention-title">
            <div>
              <h2 id="retention-title" className="flex items-center gap-2 text-sm font-semibold text-white">
                <Database className="h-4 w-4 text-cyan-400" /> Retention
              </h2>
              <p className="mt-1 text-xs text-slate-400">How many days this workspace keeps each kind of record.</p>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {RETENTION_FIELDS.map((f) => {
                const problem = dayProblem(f.key, f.min);
                const id = `ret-${f.key}`;
                return (
                  <div key={f.key}>
                    <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-300">{f.label}, in days</label>
                    <input
                      id={id}
                      inputMode="numeric"
                      value={days[f.key]}
                      disabled={!isAdmin}
                      onChange={(e) => { changed(); setDays({ ...days, [f.key]: e.target.value }); }}
                      aria-invalid={!!problem}
                      data-testid={id}
                      className={`${INPUT} ${problem ? 'border-rose-500/70' : 'border-slate-600'}`}
                    />
                    {problem
                      ? <p className="mt-1 text-xs text-rose-300">{problem}</p>
                      : <p className="mt-1 text-xs text-slate-500">At least {f.min} days</p>}
                  </div>
                );
              })}
            </div>
            <p data-testid="retention-note" className="text-xs text-slate-500">
              Once saved, a job deletes data past these days every night at 03:00 UTC. Deleted data cannot be restored.
              {isAdmin && (
                <>
                  {' '}Table archiving is set separately under <Link href="/admin/archives" className="text-cyan-300 hover:underline">Archives</Link>.
                </>
              )}
            </p>
          </section>

          {isAdmin && (
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={save}
                disabled={!canSave}
                title={disabledReason}
                data-testid="data-settings-save-bottom"
                className="inline-flex min-h-[40px] items-center justify-center gap-1.5 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? 'Saving' : 'Save changes'}
              </button>
              {status()}
            </div>
          )}
        </>
      )}
    </div>
  );
}
