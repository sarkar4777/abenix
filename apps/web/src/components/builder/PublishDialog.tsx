'use client';

import { useEffect, useState } from 'react';
import { Globe, Loader2, Lock, Rocket, Shield, Users, X } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { useApi } from '@/hooks/useApi';
import { toastSuccess } from '@/stores/toastStore';
import { usePlatformFeatures } from '@/hooks/usePlatformFeatures';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CATEGORIES = [
  'productivity',
  'research',
  'engineering',
  'creative',
  'data',
  'customer-support',
  'sales',
  'hr',
  'legal',
  'finance',
  'other',
];

type Visibility = 'tenant' | 'specific' | 'public';

const VISIBILITY_TESTID: Record<Visibility, string> = {
  tenant: 'publish-visibility-org',
  specific: 'publish-visibility-people',
  public: 'publish-visibility-public',
};

const NO_MARKETPLACE_TEXT = 'Your role cannot publish to the marketplace. Ask an admin to make you a creator.';

interface PublishDialogProps {
  open: boolean;
  onClose: () => void;
  agentId: string;
  currentCategory?: string | null;
  currentPrice?: number | null;
  onPublished: () => void;
}

export default function PublishDialog({
  open,
  onClose,
  agentId,
  currentCategory,
  currentPrice,
  onPublished,
}: PublishDialogProps) {
  const [pricingMode, setPricingMode] = useState<'free' | 'paid'>(
    currentPrice && currentPrice > 0 ? 'paid' : 'free'
  );
  const [price, setPrice] = useState(String(currentPrice || ''));
  const [category, setCategory] = useState(currentCategory || '');
  const [visibility, setVisibility] = useState<Visibility>('tenant');
  const [shareEmails, setShareEmails] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [errorLink, setErrorLink] = useState<string | null>(null);
  const [publishedWithIssues, setPublishedWithIssues] = useState(false);
  const { data: perms } = useApi<{ features?: Record<string, boolean> }>(open ? '/api/me/permissions' : null);
  const canPublishPublic = perms?.features?.publish_to_marketplace !== false;
  const { marketplace: MARKETPLACE_ON, monetization: MONETIZATION_ENABLED } = usePlatformFeatures();

  useEffect(() => {
    if (!MARKETPLACE_ON && visibility === 'public') setVisibility('tenant');
  }, [MARKETPLACE_ON, visibility]);

  useEffect(() => {
    if (!canPublishPublic && visibility === 'public') setVisibility('tenant');
  }, [canPublishPublic, visibility]);

  // Load existing shares when dialog opens
  useEffect(() => {
    if (!open || !agentId) return;
    const token = localStorage.getItem('access_token');
    if (!token) return;
    fetch(`${API_URL}/api/agents/${agentId}/shares`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.ok ? r.json() : null)
      .then((body) => {
        if (body?.data?.length > 0) {
          setVisibility('specific');
          const emails = body.data.map((s: { shared_with_email?: string }) => s.shared_with_email).filter(Boolean);
          setShareEmails(emails.join(', '));
        }
      })
      .catch(() => {});
  }, [open, agentId]);

  const handleSubmit = async () => {
    setError('');
    setErrorLink(null);
    if (MONETIZATION_ENABLED && pricingMode === 'paid' && (!price || parseFloat(price) <= 0)) {
      setError('Please enter a valid price');
      return;
    }

    setSubmitting(true);
    try {
      const token = localStorage.getItem('access_token');
      const body: Record<string, unknown> = {};

      if (MONETIZATION_ENABLED) {
        body.marketplace_price = pricingMode === 'paid' ? parseFloat(price) : null;
      }
      if (category) {
        body.category = category;
      }
      body.visibility = visibility;

      const res = await fetch(`${API_URL}/api/agents/${agentId}/publish`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data.error?.message || 'Failed to publish');
        setErrorLink(data.error?.details?.link || null);
        return;
      }

      // Specific-people grants are ResourceShare rows via POST /share
      if (visibility === 'specific' && shareEmails.trim()) {
        const emails = shareEmails.split(',').map((e) => e.trim()).filter(Boolean);
        const failures: string[] = [];
        for (const email of emails) {
          try {
            const r = await fetch(`${API_URL}/api/agents/${agentId}/share`, {
              method: 'POST',
              headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ email, permission: 'execute' }),
            });
            if (!r.ok) {
              const b = await r.json().catch(() => null);
              failures.push(`${email}: ${b?.error?.message || `HTTP ${r.status}`}`);
            }
          } catch {
            failures.push(`${email}: network error`);
          }
        }
        if (failures.length > 0) {
          // stay open so the failures can be read and fixed
          setError(`Published, but some shares failed. ${failures.join(' | ')}. Fix the addresses and publish again, or continue.`);
          setPublishedWithIssues(true);
          return;
        }
      }

      if (visibility === 'public') {
        toastSuccess('Submitted for review', 'An admin approves it, then it shows in the Marketplace. Track it in Creator Hub.');
      }
      onPublished();
      onClose();
    } catch {
      setError('Network error');
    } finally {
      setSubmitting(false);
    }
  };

  const visibilityOptions: { value: Visibility; label: string; description: string; icon: typeof Lock }[] = [
    {
      value: 'tenant',
      label: 'My Organization',
      description: 'Only members of your organization can discover and execute this agent',
      icon: Shield,
    },
    {
      value: 'specific',
      label: 'Specific People',
      description: 'Only people you explicitly share with can execute this agent',
      icon: Users,
    },
    ...(MARKETPLACE_ON ? [{
      value: 'public' as Visibility,
      label: 'Marketplace (Public)',
      description: 'Anyone can discover this agent on the marketplace',
      icon: Globe,
    }] : []),
  ];

  return (
    <ResponsiveModal
      open={open}
      onClose={onClose}
      title={MARKETPLACE_ON ? 'Publish to Marketplace' : 'Publish Agent'}
      icon={<Rocket className="w-4 h-4" />}
      maxWidth="max-w-lg"
    >
      <div className="space-y-5">
        {/* Visibility */}
        <div>
          <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
            Visibility & Access
          </label>
          <div className="space-y-2">
            {visibilityOptions.map((opt) => {
              const Icon = opt.icon;
              const blocked = opt.value === 'public' && !canPublishPublic;
              return (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => { if (!blocked) setVisibility(opt.value); }}
                  disabled={blocked}
                  aria-pressed={visibility === opt.value}
                  data-testid={VISIBILITY_TESTID[opt.value]}
                  className={`w-full flex items-start gap-3 p-3 rounded-lg border text-left transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                    visibility === opt.value
                      ? 'bg-cyan-500/10 border-cyan-500/30'
                      : 'border-slate-700 hover:border-slate-600'
                  }`}
                >
                  <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${visibility === opt.value ? 'text-cyan-400' : 'text-slate-500'}`} />
                  <div>
                    <p className={`text-sm font-medium ${visibility === opt.value ? 'text-cyan-400' : 'text-slate-300'}`}>
                      {opt.label}
                    </p>
                    <p className="text-[10px] text-slate-500 mt-0.5">{blocked ? NO_MARKETPLACE_TEXT : opt.description}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Share with specific people */}
        {visibility === 'specific' && (
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
              Share With (Email Addresses)
            </label>
            <textarea
              value={shareEmails}
              onChange={(e) => setShareEmails(e.target.value)}
              placeholder="user@example.com, another@example.com"
              rows={2}
              className="w-full px-3 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-cyan-500/50 resize-none"
            />
            <p className="text-[9px] text-slate-600 mt-1">Comma-separated. These users will get execute permission.</p>
          </div>
        )}

        {/* Pricing — only when marketplace is enabled AND visibility is public */}
        {MONETIZATION_ENABLED && visibility === 'public' && (
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
              Pricing
            </label>
            <div className="flex gap-2">
              <button
                onClick={() => setPricingMode('free')}
                className={`flex-1 py-2.5 text-sm rounded-lg border transition-colors ${
                  pricingMode === 'free'
                    ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                    : 'border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                Free
              </button>
              <button
                onClick={() => setPricingMode('paid')}
                className={`flex-1 py-2.5 text-sm rounded-lg border transition-colors ${
                  pricingMode === 'paid'
                    ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                    : 'border-slate-700 text-slate-400 hover:border-slate-600'
                }`}
              >
                Paid
              </button>
            </div>
            {pricingMode === 'paid' && (
              <div className="mt-3 relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm">$</span>
                <input
                  type="number"
                  min="0.50"
                  step="0.01"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  placeholder="9.99"
                  className="w-full pl-7 pr-14 py-2.5 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 text-xs">/ month</span>
              </div>
            )}
          </div>
        )}

        {/* Category */}
        <div>
          <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
            Category
          </label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full py-2.5 px-3 bg-slate-900/50 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-cyan-500/50 appearance-none"
          >
            <option value="">Select a category</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c.charAt(0).toUpperCase() + c.slice(1).replace('-', ' ')}
              </option>
            ))}
          </select>
        </div>

        {/* Info banner */}
        <div className="bg-slate-900/30 border border-slate-700/30 rounded-lg p-3">
          <p className="text-xs text-slate-400">
            {visibility === 'tenant' && 'This agent will be available to all members of your organization.'}
            {visibility === 'specific' && 'Only the people you specify will be able to execute this agent.'}
            {visibility === 'public' && (
              <>
                Your agent will be submitted for review before going live on the marketplace.
                {!MONETIZATION_ENABLED && ' Listings are free to install.'}
                {MONETIZATION_ENABLED && pricingMode === 'paid' && ' A 20% platform fee applies to all paid subscriptions.'}
              </>
            )}
          </p>
        </div>

        {error && (
          <p className="text-sm text-red-400" role="alert" data-testid="publish-error">
            {error}
            {errorLink && <> <a href={errorLink} className="underline hover:text-red-300">See the failing run</a></>}
          </p>
        )}
        {publishedWithIssues && (
          <button
            onClick={() => { onPublished(); onClose(); }}
            data-testid="publish-continue"
            className="w-full py-2 text-sm text-slate-300 border border-slate-600 rounded-lg hover:text-white hover:border-slate-500"
          >
            Continue to the agent
          </button>
        )}

        <button
          onClick={handleSubmit}
          disabled={submitting}
          data-testid="publish-submit"
          className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 disabled:opacity-50 transition-all flex items-center justify-center gap-2"
        >
          {submitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {visibility === 'public' ? 'Submitting...' : 'Publishing...'}
            </>
          ) : (
            <>
              <Rocket className="w-4 h-4" />
              {visibility === 'public' ? 'Submit for Review' : 'Publish Agent'}
            </>
          )}
        </button>
      </div>
    </ResponsiveModal>
  );
}
