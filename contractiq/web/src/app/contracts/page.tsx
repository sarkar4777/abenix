'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FileSearch, Upload, BarChart3, MessageSquare, FileText, TrendingUp,
  LogOut, Search, ChevronLeft, ChevronRight, Trash2, Zap,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';

function getToken() {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('contractiq_token');
}
function getUser() {
  if (typeof window === 'undefined') return null;
  try { return JSON.parse(localStorage.getItem('contractiq_user') || 'null'); } catch { return null; }
}

const NAV_ITEMS = [
  { label: 'Dashboard', icon: BarChart3, href: '/dashboard' },
  { label: 'Upload Contract', icon: Upload, href: '/upload' },
  { label: 'My Contracts', icon: FileText, href: '/contracts' },
  { label: 'Compare', icon: TrendingUp, href: '/compare' },
  { label: 'Chat', icon: MessageSquare, href: '/chat' },
];

interface Contract {
  id: string; title: string; contract_type: string; status: string;
  counterparty_a: string; counterparty_b?: string; risk_score: number | null;
  total_capacity_mw: number | null; created_at: string;
}

const TYPE_COLORS: Record<string, string> = {
  ppa: 'bg-emerald-500/10 text-emerald-400', gas: 'bg-amber-500/10 text-amber-400',
  tolling: 'bg-purple-500/10 text-purple-400', vppa: 'bg-cyan-500/10 text-cyan-400',
};
const STATUS_COLORS: Record<string, string> = {
  uploaded: 'bg-slate-500/10 text-slate-400', extracting: 'bg-cyan-500/10 text-cyan-400',
  analyzed: 'bg-emerald-500/10 text-emerald-400', error: 'bg-red-500/10 text-red-400',
};

export default function ContractListPage() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sort, setSort] = useState('newest');
  const [page, setPage] = useState(1);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const perPage = 20;

  useEffect(() => {
    const token = getToken();
    if (!token) { router.replace('/'); return; }
    setUser(getUser());
  }, [router]);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    const token = getToken();
    const params = new URLSearchParams({ limit: String(perPage), offset: String((page - 1) * perPage), sort });
    if (query) params.set('search', query);
    if (typeFilter) params.set('contract_type', typeFilter);
    if (statusFilter) params.set('status', statusFilter);
    fetch(`${API_URL}/api/contractiq/contracts?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(body => { setContracts(body.data || []); setTotal(body.meta?.total || 0); setLoading(false); })
      .catch(() => setLoading(false));
  }, [user, page, sort, query, typeFilter, statusFilter]);

  const handleDelete = async (id: string) => {
    const token = getToken();
    await fetch(`${API_URL}/api/contractiq/contracts/${id}`, {
      method: 'DELETE', headers: { Authorization: `Bearer ${token}` },
    });
    setContracts(prev => prev.filter(c => c.id !== id));
    setTotal(prev => prev - 1);
    setDeleteId(null);
  };

  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const logout = () => { localStorage.removeItem('contractiq_token'); localStorage.removeItem('contractiq_refresh_token'); localStorage.removeItem('contractiq_user'); router.replace('/'); };

  if (!user) return <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>;

  return (
    <div className="min-h-screen bg-[#0B0F19]">
      <div className="p-6">
        <div className="max-w-6xl mx-auto space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold text-white">My Contracts</h1>
              <p className="text-sm text-slate-400 mt-1">{total} contract{total !== 1 ? 's' : ''} in portfolio</p>
            </div>
            <a href="/upload"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-500 text-white text-sm font-medium hover:bg-emerald-400 transition-colors">
              <Upload className="w-4 h-4" /> Upload
            </a>
          </div>

          {/* Portfolio Quick Stats */}
          {contracts.length > 0 && (
            <div className="grid grid-cols-4 gap-3">
              {[
                { label: 'Total Capacity', value: `${contracts.reduce((s, c) => s + (c.total_capacity_mw || 0), 0).toFixed(0)} MW`, color: 'text-cyan-400' },
                { label: 'Analyzed', value: `${contracts.filter(c => c.status === 'analyzed').length}/${contracts.length}`, color: 'text-emerald-400' },
                { label: 'Avg Risk', value: (() => { const scored = contracts.filter(c => c.risk_score != null); return scored.length ? (scored.reduce((s, c) => s + (c.risk_score || 0), 0) / scored.length).toFixed(0) : '--'; })(), color: (() => { const scored = contracts.filter(c => c.risk_score != null); const avg = scored.length ? scored.reduce((s, c) => s + (c.risk_score || 0), 0) / scored.length : 0; return avg > 60 ? 'text-red-400' : avg > 35 ? 'text-amber-400' : 'text-emerald-400'; })() },
                { label: 'High Risk', value: `${contracts.filter(c => (c.risk_score || 0) > 60).length}`, color: 'text-red-400' },
              ].map(s => (
                <div key={s.label} className="bg-slate-800/20 border border-slate-700/30 rounded-lg px-3 py-2 flex items-center justify-between">
                  <span className="text-[10px] text-slate-500 uppercase">{s.label}</span>
                  <span className={`text-sm font-bold ${s.color}`}>{s.value}</span>
                </div>
              ))}
            </div>
          )}

          {/* Filters */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input type="text" placeholder="Search by title or counterparty..." value={query}
                onChange={e => { setQuery(e.target.value); setPage(1); }}
                className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-10 pr-4 py-2 text-white text-sm placeholder-slate-500 focus:border-emerald-500 focus:outline-none" />
            </div>
            <select value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setPage(1); }}
              className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none">
              <option value="">All Types</option>
              <option value="ppa">PPA</option><option value="gas">Gas</option>
              <option value="tolling">Tolling</option><option value="vppa">VPPA</option>
            </select>
            <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
              className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none">
              <option value="">All Status</option>
              <option value="uploaded">Uploaded</option><option value="extracting">Extracting</option>
              <option value="analyzed">Analyzed</option><option value="error">Error</option>
            </select>
            <select value={sort} onChange={e => { setSort(e.target.value); setPage(1); }}
              className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none">
              <option value="newest">Newest</option><option value="oldest">Oldest</option>
              <option value="name">Name</option><option value="risk">Risk</option>
            </select>
          </div>

          {/* Contract cards */}
          {loading ? (
            <div className="flex justify-center py-20"><div className="w-8 h-8 border-2 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" /></div>
          ) : contracts.length === 0 ? (
            <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-12 text-center">
              <FileText className="w-8 h-8 text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-500">No contracts found</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3">
              {contracts.map(c => (
                <motion.div key={c.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                  className="group bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600 transition-colors cursor-pointer flex items-center gap-4"
                  onClick={() => router.push(`/contracts/${c.id}`)}>
                  <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center flex-shrink-0">
                    <Zap className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-white truncate">{c.title}</p>
                    <p className="text-xs text-slate-500">{c.counterparty_a || 'No counterparty'}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${TYPE_COLORS[c.contract_type] || 'bg-slate-500/10 text-slate-400'}`}>
                    {c.contract_type?.toUpperCase()}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[c.status] || 'bg-slate-500/10 text-slate-400'}`}>
                    {c.status}
                  </span>
                  <div className="flex items-center gap-1.5 w-20">
                    <div className="flex-1 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full transition-all ${
                        c.risk_score == null ? 'w-0' :
                        c.risk_score > 70 ? 'bg-red-500' : c.risk_score > 40 ? 'bg-amber-500' : 'bg-emerald-500'
                      }`} style={{ width: `${Math.min(100, c.risk_score || 0)}%` }} />
                    </div>
                    <span className={`text-xs font-mono w-6 text-right ${
                      c.risk_score == null ? 'text-slate-600' :
                      c.risk_score > 70 ? 'text-red-400' : c.risk_score > 40 ? 'text-amber-400' : 'text-emerald-400'
                    }`}>{c.risk_score != null ? c.risk_score.toFixed(0) : '--'}</span>
                  </div>
                  {c.total_capacity_mw != null && (
                    <span className="text-xs text-slate-500 w-16 text-right">{c.total_capacity_mw} MW</span>
                  )}
                  <span className="text-xs text-slate-600 w-20 text-right">{new Date(c.created_at).toLocaleDateString()}</span>
                  <button onClick={e => { e.stopPropagation(); setDeleteId(c.id); }}
                    className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-400 transition-all p-1">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </motion.div>
              ))}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 disabled:opacity-30 transition-colors">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-xs text-slate-400 px-3">Page {page} of {totalPages}</span>
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
                className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800/50 disabled:opacity-30 transition-colors">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation modal */}
      <AnimatePresence>
        {deleteId && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setDeleteId(null)}>
            <motion.div initial={{ scale: 0.95 }} animate={{ scale: 1 }} exit={{ scale: 0.95 }}
              className="bg-slate-900 border border-slate-700 rounded-xl p-6 max-w-sm w-full mx-4" onClick={e => e.stopPropagation()}>
              <h3 className="text-sm font-semibold text-white mb-2">Delete Contract?</h3>
              <p className="text-xs text-slate-400 mb-4">This action cannot be undone. All extracted data will be permanently removed.</p>
              <div className="flex gap-3">
                <button onClick={() => setDeleteId(null)}
                  className="flex-1 px-4 py-2 rounded-lg border border-slate-700 text-sm text-slate-400 hover:text-white transition-colors">Cancel</button>
                <button onClick={() => handleDelete(deleteId)}
                  className="flex-1 px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-sm text-red-400 hover:bg-red-500/20 transition-colors">Delete</button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
