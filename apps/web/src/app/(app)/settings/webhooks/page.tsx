'use client';

import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  Webhook, Plus, Trash2, Loader2, ChevronDown, ChevronRight,
  AlertTriangle, CheckCircle2, XCircle, Clock,
} from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { toastSuccess, toastError } from '@/stores/toastStore';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const EVENT_TYPES = [
  { value: 'execution.completed', label: 'Execution Completed', description: 'Fires when an agent execution finishes successfully' },
  { value: 'execution.failed', label: 'Execution Failed', description: 'Fires when an agent execution fails' },
  { value: 'execution.started', label: 'Execution Started', description: 'Fires when an agent execution begins' },
  { value: 'agent.published', label: 'Agent Published', description: 'Fires when an agent is published to marketplace' },
  { value: 'agent.updated', label: 'Agent Updated', description: 'Fires when an agent configuration changes' },
  { value: '*', label: 'All Events', description: 'Subscribe to every event type' },
];

interface WebhookConfig {
  id: string;
  url: string;
  events: string[];
  signing_secret: string;
  is_active: boolean;
  failure_count: number;
  created_at: string;
}

function CreateWebhookModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [url, setUrl] = useState('');
  const [selectedEvents, setSelectedEvents] = useState<string[]>(['execution.completed', 'execution.failed']);
  const [creating, setCreating] = useState(false);

  const toggleEvent = (eventType: string) => {
    if (eventType === '*') {
      setSelectedEvents(['*']);
      return;
    }
    setSelectedEvents((prev) => {
      const without = prev.filter((e) => e !== '*');
      return without.includes(eventType)
        ? without.filter((e) => e !== eventType)
        : [...without, eventType];
    });
  };

  const handleCreate = async () => {
    if (!url || selectedEvents.length === 0) return;
    const token = localStorage.getItem('access_token');
    if (!token) return;

    setCreating(true);
    try {
      const res = await fetch(`${API_URL}/api/webhooks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ url, events: selectedEvents }),
      });
      const json = await res.json();
      if (json.error) {
        toastError(json.error);
      } else {
        toastSuccess('Webhook created. Copy the signing secret now — it won\'t be shown again.');
        onCreated();
        onClose();
      }
    } catch {
      toastError('Failed to create webhook');
    } finally {
      setCreating(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-[#0F172A] border border-slate-700 rounded-xl shadow-2xl w-full max-w-lg p-6">
        <h3 className="text-lg font-semibold text-white mb-4">Add Webhook Endpoint</h3>

        <div className="mb-4">
          <label className="block text-xs text-slate-400 mb-1.5">Endpoint URL</label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-app.com/api/webhook"
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>

        <div className="mb-6">
          <label className="block text-xs text-slate-400 mb-2">Events to Subscribe</label>
          <div className="space-y-2">
            {EVENT_TYPES.map((evt) => (
              <label
                key={evt.value}
                className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  selectedEvents.includes(evt.value)
                    ? 'bg-cyan-500/5 border-cyan-500/30'
                    : 'bg-slate-800/30 border-slate-700/30 hover:border-slate-600'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedEvents.includes(evt.value)}
                  onChange={() => toggleEvent(evt.value)}
                  className="mt-0.5 rounded border-slate-600 bg-slate-800 text-cyan-500 focus:ring-cyan-500"
                />
                <div>
                  <span className="text-sm text-white font-medium">{evt.label}</span>
                  <p className="text-[10px] text-slate-500">{evt.description}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-400 hover:text-white">
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!url || selectedEvents.length === 0 || creating}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-all"
          >
            {creating && <Loader2 className="w-4 h-4 animate-spin" />}
            Create Webhook
          </button>
        </div>
      </div>
    </div>
  );
}

interface DeliveryLog {
  id: string;
  event: string;
  delivered: boolean;
  response_status_code: number | null;
  attempts: number;
  error_message: string | null;
  created_at: string | null;
}

const API_INTERNAL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function WebhooksSettingsPage() {
  usePageTitle('Webhooks');
  const [showCreate, setShowCreate] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<DeliveryLog[]>([]);
  const [loadingDeliveries, setLoadingDeliveries] = useState(false);

  const loadDeliveries = async (webhookId: string) => {
    if (expandedId === webhookId) { setExpandedId(null); return; }
    setExpandedId(webhookId);
    setLoadingDeliveries(true);
    try {
      const token = localStorage.getItem('access_token');
      const res = await fetch(`${API_INTERNAL}/api/webhooks/${webhookId}/deliveries?limit=20`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const json = await res.json();
      setDeliveries(json.data || []);
    } catch { setDeliveries([]); }
    setLoadingDeliveries(false);
  };

  const { data: webhooks, mutate } = useApi<WebhookConfig[]>('/api/webhooks');

  const deleteWebhook = useCallback(async (webhookId: string) => {
    const token = localStorage.getItem('access_token');
    if (!token) return;
    try {
      await fetch(`${API_URL}/api/webhooks/${webhookId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      mutate();
      toastSuccess('Webhook deleted');
    } catch {
      toastError('Failed to delete webhook');
    }
  }, [mutate]);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-white">Webhook Endpoints</h1>
          <p className="text-sm text-slate-400 mt-1">
            Receive real-time notifications when events occur in your workspace
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          Add Endpoint
        </button>
      </div>

      {/* Info box */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 mb-6">
        <h4 className="text-sm font-medium text-white mb-2">How Webhooks Work</h4>
        <p className="text-xs text-slate-400 mb-2">
          When subscribed events occur, Abenix sends a POST request to your endpoint with a JSON payload.
          Each request includes an HMAC-SHA256 signature in the <code className="bg-slate-800 px-1 rounded">X-Abenix-Signature</code> header.
        </p>
        <p className="text-xs text-slate-400">
          Verify the signature using your signing secret. Webhooks auto-disable after 10 consecutive failures.
        </p>
      </div>

      <div className="space-y-3">
        {(!webhooks || webhooks.length === 0) && (
          <div className="text-center py-16 bg-slate-800/30 border border-slate-700/50 rounded-xl">
            <Webhook className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white mb-1">No webhook endpoints</h3>
            <p className="text-sm text-slate-500">
              Add a webhook endpoint to start receiving event notifications.
            </p>
          </div>
        )}

        {(webhooks || []).map((wh) => (
          <div key={wh.id} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-start gap-3">
              <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${
                wh.is_active ? 'bg-emerald-500/10' : 'bg-red-500/10'
              }`}>
                {wh.is_active ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-400" />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <code className="text-xs font-mono text-cyan-400 truncate">{wh.url}</code>
                  {!wh.is_active && (
                    <span className="text-[10px] bg-red-500/10 text-red-400 px-2 py-0.5 rounded-full">
                      Disabled
                    </span>
                  )}
                  {wh.failure_count > 0 && (
                    <span className="flex items-center gap-1 text-[10px] bg-amber-500/10 text-amber-400 px-2 py-0.5 rounded-full">
                      <AlertTriangle className="w-3 h-3" />
                      {wh.failure_count} failures
                    </span>
                  )}
                </div>

                {/* Events */}
                <div className="flex flex-wrap gap-1 mb-2">
                  {wh.events.map((evt) => (
                    <span key={evt} className="text-[10px] bg-slate-700/50 text-slate-400 px-2 py-0.5 rounded-full">
                      {evt}
                    </span>
                  ))}
                </div>

                {/* Signing secret info */}
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-500">Signing secret:</span>
                  <code className="text-[10px] font-mono text-slate-500 bg-slate-900/50 px-2 py-0.5 rounded">
                    whsec_••••••••••••
                  </code>
                  <span className="text-[9px] text-slate-600">
                    (shown once on creation)
                  </span>
                </div>
              </div>

              <div className="flex flex-col gap-1 shrink-0">
                <button
                  onClick={() => loadDeliveries(wh.id)}
                  className="p-2 text-slate-400 hover:text-cyan-400 hover:bg-cyan-500/10 rounded-lg transition-colors"
                  title="View delivery history"
                >
                  {expandedId === wh.id ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => deleteWebhook(wh.id)}
                  className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Delivery History (expandable) */}
            {expandedId === wh.id && (
              <div className="mt-3 pt-3 border-t border-slate-700/30">
                <h4 className="text-[10px] font-semibold text-slate-400 uppercase mb-2 flex items-center gap-1.5">
                  <Clock className="w-3 h-3" />
                  Recent Deliveries
                </h4>
                {loadingDeliveries ? (
                  <div className="flex items-center gap-2 py-4 justify-center text-slate-500 text-xs">
                    <Loader2 className="w-4 h-4 animate-spin" /> Loading...
                  </div>
                ) : deliveries.length === 0 ? (
                  <p className="text-[10px] text-slate-600 py-2">No deliveries recorded yet.</p>
                ) : (
                  <div className="space-y-1">
                    {deliveries.map((d) => (
                      <div key={d.id} className="flex items-center gap-3 px-2 py-1.5 bg-slate-900/30 rounded text-[10px]">
                        {d.delivered ? (
                          <CheckCircle2 className="w-3 h-3 text-emerald-400 shrink-0" />
                        ) : (
                          <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                        )}
                        <span className="text-slate-400 font-mono">{d.event}</span>
                        <span className={`font-mono ${d.delivered ? 'text-emerald-400' : 'text-red-400'}`}>
                          {d.response_status_code || 'ERR'}
                        </span>
                        <span className="text-slate-600">{d.attempts} attempt{d.attempts !== 1 ? 's' : ''}</span>
                        {d.error_message && (
                          <span className="text-red-400 truncate max-w-[200px]" title={d.error_message}>{d.error_message}</span>
                        )}
                        <span className="text-slate-600 ml-auto">
                          {d.created_at ? new Date(d.created_at).toLocaleString() : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <CreateWebhookModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={() => mutate()}
      />
    </motion.div>
  );
}
