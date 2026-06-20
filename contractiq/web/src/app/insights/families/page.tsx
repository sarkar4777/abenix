'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Layers, ChevronLeft, Plus, Trash2, Edit3, Save, X,
  Loader2, FileText, Crown,
} from 'lucide-react';
import { PageExplainer } from '@/components/PageExplainer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { return typeof window !== 'undefined' ? localStorage.getItem('contractiq_token') : null; }

interface Family {
  id: string;
  family_name: string;
  description: string | null;
  master_contract_id: string | null;
  member_contract_ids: string[];
  created_at: string;
  updated_at: string;
}

interface Contract { id: string; title: string; }

export default function FamiliesPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // Form
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [master, setMaster] = useState('');
  const [members, setMembers] = useState<string[]>([]);

  const load = async () => {
    setLoading(true);
    const token = getToken();
    if (!token) return;
    const [fRes, cRes] = await Promise.all([
      fetch(`${API_URL}/api/contractiq/insights/families`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${API_URL}/api/contractiq/contracts?limit=200`, { headers: { Authorization: `Bearer ${token}` } }),
    ]);
    setFamilies((await fRes.json()).data || []);
    setContracts(((await cRes.json()).data || []).map((c: any) => ({ id: c.id, title: c.title })));
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  const startCreate = () => {
    setCreating(true); setEditing(null);
    setName(''); setDescription(''); setMaster(''); setMembers([]);
  };
  const startEdit = (f: Family) => {
    setEditing(f.id); setCreating(false);
    setName(f.family_name); setDescription(f.description || '');
    setMaster(f.master_contract_id || ''); setMembers(f.member_contract_ids || []);
  };
  const cancel = () => { setEditing(null); setCreating(false); };

  const save = async () => {
    if (!name.trim()) return;
    const token = getToken();
    const body = { family_name: name.trim(), description: description || null, master_contract_id: master || null, member_contract_ids: members };
    if (creating) {
      await fetch(`${API_URL}/api/contractiq/insights/families`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } else if (editing) {
      await fetch(`${API_URL}/api/contractiq/insights/families/${editing}`, {
        method: 'PUT',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    }
    cancel();
    await load();
  };

  const remove = async (id: string) => {
    if (!confirm('Delete this family?')) return;
    const token = getToken();
    await fetch(`${API_URL}/api/contractiq/insights/families/${id}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    await load();
  };

  const titleOf = (id: string) => contracts.find(c => c.id === id)?.title || id.slice(0, 8);

  return (
    <div className="min-h-screen bg-[#0B0F19] p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <a href="/insights" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-emerald-400 mb-2">
              <ChevronLeft className="w-3 h-3" /> Back to Insights Hub
            </a>
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-600/20 border border-indigo-500/30 flex items-center justify-center">
                <Layers className="w-6 h-6 text-indigo-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-white">Contract Families</h1>
                <PageExplainer routeKey="insights-families" />
                <p className="text-xs text-slate-400">Group master contracts with their amendments and side letters</p>
              </div>
            </div>
          </div>
          <button onClick={startCreate} className="px-4 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-purple-600 text-white text-sm font-semibold hover:shadow-lg hover:shadow-indigo-500/25 transition-all flex items-center gap-2">
            <Plus className="w-4 h-4" /> New Family
          </button>
        </div>

        {/* Editor */}
        {(creating || editing) && (
          <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-5 mb-6">
            <h3 className="text-sm font-semibold text-white mb-3">{creating ? 'New Family' : 'Edit Family'}</h3>
            <div className="space-y-3">
              <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="Family name (e.g. Al Dhafra Solar PPA + Amendments)"
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-indigo-500 focus:outline-none" />
              <input type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="Description (optional)"
                className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-indigo-500 focus:outline-none" />
              <div>
                <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Master Contract</label>
                <select value={master} onChange={e => setMaster(e.target.value)}
                  className="w-full bg-slate-900/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-indigo-500 focus:outline-none">
                  <option value="">— No master —</option>
                  {contracts.map(c => <option key={c.id} value={c.id}>{c.title}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-slate-400 uppercase tracking-wider mb-1 block">Member Contracts (incl. amendments)</label>
                <div className="max-h-48 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900/30 p-2 space-y-1">
                  {contracts.map(c => (
                    <label key={c.id} className="flex items-center gap-2 text-xs text-slate-300 hover:text-white cursor-pointer p-1 rounded hover:bg-slate-800/50">
                      <input type="checkbox" checked={members.includes(c.id)} onChange={e => {
                        if (e.target.checked) setMembers([...members, c.id]);
                        else setMembers(members.filter(m => m !== c.id));
                      }} />
                      <span className="flex-1 truncate">{c.title}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={save} disabled={!name.trim()} className="px-4 py-2 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-xs font-semibold hover:bg-emerald-500/30 transition-colors disabled:opacity-50 flex items-center gap-1.5">
                  <Save className="w-3.5 h-3.5" /> Save
                </button>
                <button onClick={cancel} className="px-4 py-2 rounded-lg bg-slate-700/30 border border-slate-600/40 text-slate-400 text-xs font-semibold hover:bg-slate-700/50 transition-colors flex items-center gap-1.5">
                  <X className="w-3.5 h-3.5" /> Cancel
                </button>
              </div>
            </div>
          </motion.div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-40"><Loader2 className="w-6 h-6 animate-spin text-indigo-400" /></div>
        ) : families.length === 0 && !creating ? (
          <div className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-12 text-center">
            <Layers className="w-12 h-12 text-indigo-400/40 mx-auto mb-3" />
            <p className="text-sm text-slate-400">No contract families yet.</p>
            <p className="text-xs text-slate-500 mt-1">Group master contracts with their amendments to enable cross-document reasoning.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {families.map(f => (
              <motion.div key={f.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-semibold text-white">{f.family_name}</h3>
                    {f.description && <p className="text-xs text-slate-400 mt-0.5">{f.description}</p>}
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => startEdit(f)} className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors">
                      <Edit3 className="w-3.5 h-3.5" />
                    </button>
                    <button onClick={() => remove(f.id)} className="p-1.5 rounded hover:bg-red-500/20 text-slate-400 hover:text-red-300 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
                {f.master_contract_id && (
                  <div className="flex items-center gap-2 mb-2 text-xs">
                    <Crown className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-amber-300 font-medium">{titleOf(f.master_contract_id)}</span>
                    <span className="text-[10px] text-slate-500">(master)</span>
                  </div>
                )}
                <div className="space-y-1">
                  {f.member_contract_ids.map(id => (
                    <div key={id} className="flex items-center gap-2 text-xs text-slate-400">
                      <FileText className="w-3 h-3 text-slate-500" />
                      <span className="truncate">{titleOf(id)}</span>
                    </div>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
