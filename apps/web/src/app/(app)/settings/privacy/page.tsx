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
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';

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
  const { data: retentionData } = useApi<RetentionPolicy>('/api/settings/retention');

  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState('');
  const [saving, setSaving] = useState(false);
  const [retentionForm, setRetentionForm] = useState({
    execution_retention_days: 90,
    message_retention_days: 365,
    audit_log_retention_days: 730,
  });

  useEffect(() => {
    if (retentionData) {
      setRetentionForm({
        execution_retention_days: retentionData.execution_retention_days,
        message_retention_days: retentionData.message_retention_days,
        audit_log_retention_days: retentionData.audit_log_retention_days,
      });
    }
  }, [retentionData]);

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
        window.location.href = '/login';
      } else {
        toastError('Failed to delete account', res.error);
      }
    } catch {
      toastError('Failed to delete account');
    } finally {
      setDeleting(false);
    }
  };

  const handleSaveRetention = async () => {
    setSaving(true);
    try {
      const res = await apiFetch<RetentionPolicy>('/api/settings/retention', {
        method: 'PUT',
        body: JSON.stringify(retentionForm),
      });
      if (res.data) {
        toastSuccess('Retention policy saved');
      } else {
        toastError('Failed to save retention policy', res.error ?? undefined);
      }
    } catch {
      toastError('Failed to save retention policy');
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <div>
        <h1 className="text-2xl font-bold text-white">Privacy & Data</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage your data, retention policies, and GDPR rights
        </p>
      </div>

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

      {/* Retention Policy */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 space-y-4">
        <div className="flex items-center gap-3">
          <Clock className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-white">
            Data Retention Policy
          </h2>
        </div>
        <p className="text-xs text-slate-400">
          Configure how long data is kept before automatic cleanup.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label
              htmlFor="exec-retention"
              className="block text-xs text-slate-400 mb-1.5"
            >
              Executions (days)
            </label>
            <input
              id="exec-retention"
              type="number"
              min={7}
              value={retentionForm.execution_retention_days}
              onChange={(e) =>
                setRetentionForm((f) => ({
                  ...f,
                  execution_retention_days:
                    Math.max(7, parseInt(e.target.value) || 7),
                }))
              }
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:border-cyan-500 focus:outline-none"
            />
            <p className="text-[10px] text-slate-600 mt-0.5">Min: 7 days</p>
          </div>
          <div>
            <label
              htmlFor="msg-retention"
              className="block text-xs text-slate-400 mb-1.5"
            >
              Conversations (days)
            </label>
            <input
              id="msg-retention"
              type="number"
              min={30}
              value={retentionForm.message_retention_days}
              onChange={(e) =>
                setRetentionForm((f) => ({
                  ...f,
                  message_retention_days:
                    Math.max(30, parseInt(e.target.value) || 30),
                }))
              }
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:border-cyan-500 focus:outline-none"
            />
            <p className="text-[10px] text-slate-600 mt-0.5">Min: 30 days</p>
          </div>
          <div>
            <label
              htmlFor="audit-retention"
              className="block text-xs text-slate-400 mb-1.5"
            >
              Audit Logs (days)
            </label>
            <input
              id="audit-retention"
              type="number"
              min={365}
              value={retentionForm.audit_log_retention_days}
              onChange={(e) =>
                setRetentionForm((f) => ({
                  ...f,
                  audit_log_retention_days:
                    Math.max(365, parseInt(e.target.value) || 365),
                }))
              }
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:border-cyan-500 focus:outline-none"
            />
            <p className="text-[10px] text-slate-600 mt-0.5">
              Min: 365 days (compliance)
            </p>
          </div>
        </div>

        <button
          onClick={handleSaveRetention}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-cyan-500/20 text-cyan-400 text-sm font-medium rounded-lg hover:bg-cyan-500/30 transition-colors disabled:opacity-50"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {saving ? 'Saving...' : 'Save Retention Policy'}
        </button>
      </div>

      {/* Data Export (GDPR Article 20) */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-center gap-3 mb-4">
          <Download className="w-5 h-5 text-cyan-400" />
          <h2 className="text-lg font-semibold text-white">Export Your Data</h2>
        </div>
        <p className="text-xs text-slate-400 mb-4">
          Download a copy of all your data including profile, agents, executions,
          and conversations. This is your right under GDPR Article 20 (data
          portability).
        </p>
        <button
          onClick={handleExport}
          disabled={exporting}
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
