'use client';

import { useEscapeToClose } from '@/hooks/useEscapeToClose';
import { useState, useEffect } from 'react';
import { Loader2, Share2, Trash2, X, Users, Mail, Shield } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface Share {
  id: string;
  shared_with_email: string;
  permission: string;
  created_at: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  agentId: string;
  agentName: string;
}

export default function ShareDialog({ open, onClose, agentId, agentName }: Props) {
  const [email, setEmail] = useState('');
  const [permission, setPermission] = useState<'view' | 'execute' | 'edit'>('execute');
  const [shares, setShares] = useState<Share[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : '';

  useEffect(() => {
    if (!open || !agentId) return;
    fetch(`${API_URL}/api/agents/${agentId}/shares`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async r => {
        const b = await r.json().catch(() => null);
        if (!r.ok) {
          setError(b?.error?.message || 'Could not load shares');
          return;
        }
        setShares(b?.data || []);
      })
      .catch(() => setError('Could not load shares'));
  }, [open, agentId, token]);

  useEscapeToClose(open, onClose);
  if (!open) return null;

  const share = async () => {
    if (!email.includes('@')) { setError('Enter a valid email'); return; }
    setLoading(true); setError(null); setSuccess(null);
    try {
      const resp = await fetch(`${API_URL}/api/agents/${agentId}/share`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ email, permission }),
      });
      const body = await resp.json();
      if (resp.ok) {
        setSuccess(`Shared with ${email}`);
        setEmail('');
        setShares(prev => [...prev.filter(s => s.id !== body.data.id), body.data]);
      } else {
        setError(body.error?.message || 'Failed to share');
      }
    } catch { setError('Network error'); }
    finally { setLoading(false); }
  };

  const revoke = async (shareId: string) => {
    setError(null);
    try {
      const r = await fetch(`${API_URL}/api/agents/${agentId}/shares/${shareId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!r.ok) {
        const b = await r.json().catch(() => null);
        setError(b?.error?.message || 'Failed to revoke');
        return;
      }
      setShares(prev => prev.filter(s => s.id !== shareId));
    } catch { setError('Network error'); }
  };

  const permColors = { view: 'text-slate-400', execute: 'text-cyan-400', edit: 'text-amber-400' };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" role="dialog" aria-modal="true" aria-label={`Share ${agentName}`}>
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/50">
          <div className="flex items-center gap-2">
            <Share2 className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-white">Share "{agentName}"</h2>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <p className="text-xs text-slate-400">
            Share with someone in your organisation by their sign-in email. View lets them see it, Execute lets them run it, Edit lets them change it.
          </p>
          <div className="flex flex-wrap gap-2">
            <input
              type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="user@example.com"
              aria-label="Email to share with"
              data-testid="share-email"
              className="flex-1 min-w-[160px] px-3 py-2 text-xs bg-slate-900/50 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-cyan-500"
            />
            <select value={permission} onChange={e => setPermission(e.target.value as typeof permission)}
              aria-label="Permission" data-testid="share-permission"
              className="px-2 py-2 text-xs bg-slate-900/50 border border-slate-700 rounded-lg text-white">
              <option value="view">View</option>
              <option value="execute">Execute</option>
              <option value="edit">Edit</option>
            </select>
            <button onClick={share} disabled={loading}
              aria-label="Share" data-testid="share-submit"
              className="flex items-center gap-1.5 px-3 py-2 bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 text-xs rounded-lg hover:bg-cyan-500/30 disabled:opacity-50">
              {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Mail className="w-3 h-3" />}
              Share
            </button>
          </div>

          {error && <p role="alert" data-testid="share-error" className="text-xs text-red-400">{error}</p>}
          {success && <p data-testid="share-success" className="text-xs text-emerald-400">{success}</p>}
          {shares.length === 0 && !error && (
            <p className="text-xs text-slate-500" data-testid="share-empty">Not shared with anyone yet.</p>
          )}

          {shares.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] text-slate-500 uppercase tracking-wider">Shared with</p>
              {shares.map(s => (
                <div key={s.id} data-testid="share-row" className="flex items-center justify-between p-2 bg-slate-900/30 rounded-lg">
                  <div className="flex items-center gap-2">
                    <Users className="w-3 h-3 text-slate-500" />
                    <span className="text-xs text-slate-300">{s.shared_with_email}</span>
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${permColors[s.permission as keyof typeof permColors] || 'text-slate-400'} bg-slate-800`}>
                      {s.permission}
                    </span>
                  </div>
                  <button onClick={() => revoke(s.id)} aria-label={`Revoke access for ${s.shared_with_email}`} className="text-red-400 hover:text-red-300">
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
