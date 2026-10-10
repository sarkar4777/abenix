'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Download,
  FileText,
  Loader2,
  Shield,
  Trash2,
} from 'lucide-react';
import Link from 'next/link';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';
import PageHeader from '@/components/layout/PageHeader';

interface PrivacyInfo {
  data_processing: {
    encryption_at_rest: string;
    encryption_in_transit: string;
    data_location: string;
    password_hashing: string;
    api_key_hashing: string;
  };
  retention_policy: Record<string, number>;
  dlp_policy: Record<string, unknown>;
  gdpr_endpoints: Record<string, string>;
}

interface RetentionPolicy {
  execution_retention_days: number;
  message_retention_days: number;
  audit_log_retention_days: number;
}

export default function PrivacyPage() {
  usePageTitle('Privacy & Data');

  const { data: privacy } = useApi<PrivacyInfo>('/api/account/privacy');
  const [exportSummary, setExportSummary] = useState<string | null>(null);
  const { data: retentionData } = useApi<RetentionPolicy>('/api/settings/retention');

  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState('');

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await apiFetch('/api/account/export', { method: 'POST' });
      if (res.data) {
        const blob = new Blob([JSON.stringify(res.data, null, 2)], {
          type: 'application/json',
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `abenix-data-export-${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
        setExported(true);
        const d = res.data as Record<string, unknown[] | undefined>;
        const count = (k: string) => (Array.isArray(d[k]) ? (d[k] as unknown[]).length : 0);
        setExportSummary(
          `${count('agents')} agents, ${count('executions')} runs, ${count('conversations')} conversations with ${count('messages')} messages, ${count('sessions')} sign-ins and ${count('activity')} activity entries.`,
        );
        toastSuccess('Data exported successfully');
        setTimeout(() => setExported(false), 5000);
      } else {
        toastError('Export failed', res.error ?? undefined);
      }
    } catch {
      toastError('Failed to export data');
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async () => {
    if (confirmDelete !== 'DELETE') return;
    setDeleting(true);
    try {
      const res = await apiFetch('/api/account', { method: 'DELETE' });
      if (!res.error) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        window.location.href = '/';
      } else {
        toastError('Failed to delete account', res.error);
      }
    } catch {
      toastError('Failed to delete account');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <PageHeader
        title="Privacy & Data"
        icon={Shield}
        purpose="Download a copy of your data, see how long it is kept, or delete your account. For everyone."
        primaryAction={{
          label: exporting ? 'Exporting...' : 'Export my data',
          icon: exporting ? Loader2 : Download,
          busy: exporting,
          onClick: handleExport,
        }}
        steps={[
          'See how your data is protected at rest and on the wire.',
          'See how many days runs, chats and audit logs are kept. Admins change it under Data & DLP.',
          'Export everything about you as one JSON file at any time.',
          'Deleting your account is permanent. Type DELETE to confirm.',
        ]}
        docSlug="01-architecture/07-governance"
        storageKey="settings-privacy"
      />

      {/* Data Processing Info */}
      {privacy && (
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
          <div className="flex items-center gap-3 mb-4">
            <Shield className="w-5 h-5 text-cyan-400" />
            <h2 className="text-lg font-semibold text-white">
              Data Processing
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(privacy.data_processing).map(([key, value]) => (
              <div
                key={key}
                className="flex items-center justify-between rounded-lg bg-slate-800/50 border border-slate-700/30 p-3"
              >
                <span className="text-xs text-slate-400 capitalize">
                  {key.replace(/_/g, ' ')}
                </span>
                <span className="text-xs text-white font-mono">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Retention, read only here */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6 space-y-3" data-testid="privacy-retention">
        <div className="flex items-center gap-3">
          <Clock className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-white">How long data is kept</h2>
        </div>
        <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            ['Run history', retentionData?.execution_retention_days],
            ['Conversations', retentionData?.message_retention_days],
            ['Audit logs', retentionData?.audit_log_retention_days],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg bg-slate-800/50 border border-slate-700/30 p-3">
              <dt className="text-xs text-slate-400">{label}</dt>
              <dd className="text-sm text-white font-medium">{value ? `${value} days` : '...'}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-slate-500">
          After that, cleanup removes it for everyone in the workspace. Workspace admins change these under{' '}
          <Link href="/settings/data" className="text-cyan-300 hover:underline">Data &amp; DLP</Link>.
        </p>
      </div>

      {/* Data Export (GDPR Article 20) */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <Download className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-white">Export Your Data</h2>
        </div>
        <p className="text-xs text-slate-400 mb-4">
          Download one JSON file with your profile, agents, runs, conversations
          with their messages, API key names, your sign-ins and your own
          activity. This is your right under GDPR Article 20 (data portability).
        </p>
        <button
          onClick={handleExport}
          disabled={exporting}
          data-testid="export-data"
          className="flex items-center gap-2 px-4 py-2 bg-slate-700/50 border border-slate-600 text-sm text-white rounded-lg hover:bg-slate-700 disabled:opacity-50 transition-colors"
        >
          {exporting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : exported ? (
            <CheckCircle className="w-4 h-4 text-emerald-400" />
          ) : (
            <FileText className="w-4 h-4" />
          )}
          {exporting
            ? 'Exporting...'
            : exported
              ? 'Downloaded!'
              : 'Export All Data (JSON)'}
        </button>
        {exportSummary && (
          <p role="status" data-testid="export-summary" className="mt-3 text-xs text-emerald-300">
            The file has your profile, {exportSummary}
          </p>
        )}
      </div>

      {/* Account Deletion (GDPR Article 17) */}
      <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <Trash2 className="w-5 h-5 text-red-400" />
          <h2 className="text-lg font-semibold text-white">Delete Account</h2>
        </div>
        <div className="flex items-start gap-3 mb-4">
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-red-300 font-medium">
              This action is permanent and cannot be undone.
            </p>
            <p className="text-xs text-slate-400 mt-1">
              Your account will be deactivated, personal data anonymized, API
              keys revoked, and conversations deleted. Execution history will be
              retained anonymously for analytics.
            </p>
          </div>
        </div>
        <div className="space-y-3">
          <div>
            <label
              htmlFor="confirm-delete"
              className="block text-xs text-slate-400 mb-1.5"
            >
              Type <strong className="text-red-400">DELETE</strong> to confirm
            </label>
            <input
              id="confirm-delete"
              type="text"
              value={confirmDelete}
              onChange={(e) => setConfirmDelete(e.target.value)}
              placeholder="DELETE"
              className="w-48 px-3 py-2 bg-slate-900/50 border border-red-500/30 rounded-lg text-sm text-white focus:border-red-500 focus:outline-none"
            />
          </div>
          <button
            onClick={handleDelete}
            disabled={deleting || confirmDelete !== 'DELETE'}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {deleting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Trash2 className="w-4 h-4" />
            )}
            {deleting ? 'Deleting...' : 'Delete My Account'}
          </button>
        </div>
      </div>
    </motion.div>
  );
}
