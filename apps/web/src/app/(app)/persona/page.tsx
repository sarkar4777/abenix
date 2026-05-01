'use client';

import { useEffect, useState, useRef } from 'react';
import {
  UserCircle2, Plus, Upload, FileText, Trash2, Shield, Lock,
  Loader2, StickyNote, Tag, Calendar, Mic, MicOff, CheckCircle2, AlertTriangle,
} from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

interface PersonaItem {
  id: string;
  persona_scope: string;
  kind: string;
  title: string;
  source: string | null;
  byte_size: number;
  chunk_count: number;
  status: string;
  created_at: string | null;
}

interface VoiceState {
  voice_id: string | null;
  voice_provider: string | null;
  voice_consent_at: string | null;
  has_clone: boolean;
  elevenlabs_configured: boolean;
}

export default function PersonaPage() {
  usePageTitle('Persona KB');
  const [items, setItems] = useState<PersonaItem[]>([]);
  const [scopes, setScopes] = useState<string[]>(['self']);
  const [activeScope, setActiveScope] = useState<string>('self');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showNote, setShowNote] = useState(false);
  const [noteTitle, setNoteTitle] = useState('');
  const [noteText, setNoteText] = useState('');
  const [noteScope, setNoteScope] = useState('self');
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadScope, setUploadScope] = useState('self');
  const [uploadTitle, setUploadTitle] = useState('');
  const [newScope, setNewScope] = useState('');
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [voiceName, setVoiceName] = useState('My meeting voice');
  const [voiceUploading, setVoiceUploading] = useState(false);
  const voiceFileRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [itemsR, scopesR, voiceR] = await Promise.all([
        apiFetch<PersonaItem[]>(`/api/persona/items${activeScope ? `?scope=${encodeURIComponent(activeScope)}` : ''}`),
        apiFetch<string[]>('/api/persona/scopes'),
        apiFetch<VoiceState>('/api/persona/voice'),
      ]);
      setItems(itemsR.data || []);
      setScopes(scopesR.data || ['self']);
      setVoice(voiceR.data || null);
    } catch (e: any) {
      setErr(e?.message || 'load failed');
    }
    setLoading(false);
  };

  const uploadVoice = async () => {
    const file = voiceFileRef.current?.files?.[0];
    if (!file) { setErr('Select a clip first'); return; }
    setVoiceUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('name', voiceName || 'My meeting voice');
      const token = localStorage.getItem('access_token');
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/persona/voice/upload`,
        { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd },
      );
      const j = await r.json();
      if (j?.error) throw new Error(j.error?.message || 'upload failed');
      await load();
    } catch (e: any) {
      setErr(e?.message || 'voice upload failed');
    }
    setVoiceUploading(false);
  };

  const giveConsent = async () => {
    try {
      await apiFetch('/api/persona/voice/consent', {
        method: 'POST',
        body: JSON.stringify({
          agree: true,
          consent_text:
            'I authorize Abenix to use my cloned voice when the Meeting Representative ' +
            'agent speaks on my behalf in meetings I have explicitly authorized. I can revoke ' +
            'this consent at any time.',
        }),
      });
      await load();
    } catch (e: any) {
      setErr(e?.message || 'consent failed');
    }
  };

  const revokeVoice = async () => {
    if (!confirm('Revoke consent AND delete the cloned voice from ElevenLabs?')) return;
    try {
      await apiFetch('/api/persona/voice/revoke', { method: 'POST', body: '{}' });
      await load();
    } catch (e: any) {
      setErr(e?.message || 'revoke failed');
    }
  };

  useEffect(() => { load(); }, [activeScope]);

  const addNote = async () => {
    if (!noteText.trim()) return;
    setSaving(true);
    try {
      await apiFetch('/api/persona/notes', {
        method: 'POST',
        body: JSON.stringify({
          title: noteTitle || 'Note',
          text: noteText,
          persona_scope: noteScope,
        }),
      });
      setNoteTitle(''); setNoteText(''); setShowNote(false);
      await load();
    } catch (e: any) {
      setErr(e?.message || 'save failed');
    }
    setSaving(false);
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('title', uploadTitle || file.name);
      fd.append('persona_scope', uploadScope);
      const token = localStorage.getItem('access_token');
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/persona/upload`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: fd,
        },
      );
      const j = await r.json();
      if (j?.error) throw new Error(j.error?.message || 'upload failed');
      setUploadTitle('');
      if (fileRef.current) fileRef.current.value = '';
      await load();
    } catch (e: any) {
      setErr(e?.message || 'upload failed');
    }
    setUploading(false);
  };

  const deleteItem = async (id: string) => {
    if (!confirm('Delete this item and its vectors from the persona KB?')) return;
    try {
      await apiFetch(`/api/persona/items/${id}`, { method: 'DELETE' });
      await load();
    } catch (e: any) {
      setErr(e?.message || 'delete failed');
    }
  };

  const addScope = () => {
    const v = newScope.trim();
    if (!v) return;
    if (!/^[A-Za-z0-9:_\-\.]+$/.test(v)) {
      setErr('Scope must be alphanumeric, dash, colon, underscore, dot');
      return;
    }
    if (!scopes.includes(v)) setScopes([...scopes, v]);
    setNewScope('');
    setActiveScope(v);
  };

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
          <UserCircle2 className="w-6 h-6 text-cyan-400" />
          Persona KB
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Ring-fenced knowledge that only scope-authorized agents can retrieve.
          Data here is NEVER returned by generic knowledge searches — only by
          the <code className="text-cyan-300">persona_rag</code> tool when the
          caller's context includes the matching scope.
        </p>
        <div className="mt-2 inline-flex items-center gap-1.5 text-xs text-slate-500">
          <Lock className="w-3 h-3" />
          Hard filters: tenant_id, user_id, persona_scope. Defense-in-depth applied on read.
        </div>
      </div>

      {err && (
        <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
          {err}
        </div>
      )}

      {/* Voice clone panel */}
      <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Mic className="w-4 h-4 text-purple-400" />
            <h2 className="text-sm font-medium text-white">Voice clone</h2>
            {voice?.has_clone ? (
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/30">
                <CheckCircle2 className="w-3 h-3" /> active + consented
              </span>
            ) : voice?.voice_id ? (
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30">
                <AlertTriangle className="w-3 h-3" /> consent required
              </span>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-500/10 text-slate-400 border border-slate-500/20">
                not set
              </span>
            )}
          </div>
          {voice?.voice_id && (
            <button onClick={revokeVoice} className="text-xs text-red-400 hover:underline flex items-center gap-1">
              <MicOff className="w-3 h-3" /> Revoke + delete
            </button>
          )}
        </div>

        {!voice?.elevenlabs_configured && (
          <div className="text-xs text-amber-300/80 bg-amber-500/5 border border-amber-500/30 rounded p-2">
            ElevenLabs is not configured on this server. Set{' '}
            <code className="text-amber-200">ELEVENLABS_API_KEY</code> in{' '}
            <code className="text-amber-200">abenix-secrets</code> and roll the deployment to enable voice cloning.
          </div>
        )}

        {voice?.elevenlabs_configured && !voice?.voice_id && (
          <>
            <p className="text-xs text-slate-400">
              Upload a <strong>30-120 second WAV/MP3</strong> of yourself speaking
              naturally — ideally reading a paragraph at conversational pace in a
              quiet room. ElevenLabs clones the voice; we store only the resulting
              voice_id here. The bot CANNOT use the clone until you separately
              record consent below.
            </p>
            <div className="flex items-center gap-2">
              <input
                value={voiceName}
                onChange={e => setVoiceName(e.target.value)}
                className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white w-48"
                placeholder="Voice name"
              />
              <input
                ref={voiceFileRef}
                type="file"
                accept="audio/*"
                className="text-xs text-slate-300 file:mr-2 file:px-2 file:py-1 file:rounded file:border-0 file:bg-purple-600/30 file:text-purple-100"
                disabled={voiceUploading}
              />
              <button
                onClick={uploadVoice}
                disabled={voiceUploading}
                className="px-3 py-1.5 text-xs rounded bg-purple-600/30 border border-purple-500/40 text-purple-100 hover:bg-purple-600/50 disabled:opacity-50"
              >
                {voiceUploading ? 'Cloning…' : 'Clone voice'}
              </button>
            </div>
          </>
        )}

        {voice?.voice_id && !voice?.voice_consent_at && (
          <div className="rounded border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
            <p className="text-xs text-amber-200">
              <strong>Your voice has been cloned but is gated behind consent.</strong>
              {' '}
              The bot will fall back to the neutral OpenAI voice with a{' '}
              <code className="text-amber-300">cloned_fallback: true</code> flag
              on every utterance until you explicitly agree below.
            </p>
            <p className="text-[11px] text-amber-200/80 leading-relaxed">
              <em>By clicking "I consent"</em>: I authorize Abenix to use my
              cloned voice when the Meeting Representative agent speaks on my
              behalf in meetings I have explicitly authorized. I understand I can
              revoke this consent at any time; revocation also deletes the voice
              from the provider side.
            </p>
            <button
              onClick={giveConsent}
              className="px-3 py-1.5 text-xs rounded bg-emerald-600/30 border border-emerald-500/50 text-emerald-100 hover:bg-emerald-600/50"
            >
              <CheckCircle2 className="w-3 h-3 inline mr-1" />
              I consent
            </button>
          </div>
        )}

        {voice?.has_clone && (
          <div className="text-xs text-slate-400">
            voice_id: <code className="text-purple-300">{voice.voice_id?.slice(0, 12)}…</code>{' '}
            · provider: <code className="text-purple-300">{voice.voice_provider}</code>{' '}
            · consented: {voice.voice_consent_at ? new Date(voice.voice_consent_at).toLocaleString() : '—'}
          </div>
        )}
      </div>

      {/* Scope selector */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500 mr-2">Scope:</span>
        {scopes.map(s => (
          <button
            key={s}
            onClick={() => setActiveScope(s)}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs border ${
              activeScope === s
                ? 'bg-cyan-500/10 border-cyan-500/40 text-cyan-200'
                : 'border-slate-700/50 text-slate-400 hover:text-slate-200'
            }`}
          >
            <Tag className="w-3 h-3" />
            {s}
          </button>
        ))}
        <div className="flex items-center gap-1 ml-2">
          <input
            value={newScope}
            onChange={e => setNewScope(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addScope()}
            placeholder="new scope (e.g. client:acme)"
            className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white w-52"
          />
          <button onClick={addScope} className="px-2 py-1 text-xs rounded border border-slate-700/50 text-slate-300">
            <Plus className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Add note */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <StickyNote className="w-4 h-4 text-emerald-400" />
            <h3 className="text-sm font-medium text-white">Add a note</h3>
          </div>
          {showNote ? (
            <>
              <input
                value={noteTitle}
                onChange={e => setNoteTitle(e.target.value)}
                placeholder="Title"
                className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700/50 rounded text-sm text-white placeholder-slate-500"
              />
              <textarea
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="Anything you want your bot to know: context, preferences, facts, stance on topics."
                rows={6}
                className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700/50 rounded text-sm text-white placeholder-slate-500 resize-y"
              />
              <div className="flex items-center gap-2">
                <select
                  value={noteScope}
                  onChange={e => setNoteScope(e.target.value)}
                  className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white"
                >
                  {scopes.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <button
                  onClick={addNote}
                  disabled={saving || !noteText.trim()}
                  className="px-3 py-1.5 text-xs rounded bg-emerald-600/30 border border-emerald-500/40 text-emerald-100 hover:bg-emerald-600/50 disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save note'}
                </button>
                <button
                  onClick={() => { setShowNote(false); setNoteTitle(''); setNoteText(''); }}
                  className="px-3 py-1.5 text-xs rounded border border-slate-700/50 text-slate-400"
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <button
              onClick={() => { setShowNote(true); setNoteScope(activeScope || 'self'); }}
              className="w-full px-3 py-2 text-sm rounded border border-dashed border-slate-700 text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300"
            >
              + Add note
            </button>
          )}
        </div>

        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Upload className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-medium text-white">Upload file</h3>
            <span className="text-[10px] text-slate-500">(.txt, .md, .pdf)</span>
          </div>
          <input
            value={uploadTitle}
            onChange={e => setUploadTitle(e.target.value)}
            placeholder="Title (optional — defaults to filename)"
            className="w-full px-3 py-2 bg-slate-800/60 border border-slate-700/50 rounded text-sm text-white placeholder-slate-500"
          />
          <div className="flex items-center gap-2">
            <select
              value={uploadScope}
              onChange={e => setUploadScope(e.target.value)}
              className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white"
            >
              {scopes.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <input
              ref={fileRef}
              type="file"
              onChange={onFile}
              className="text-xs text-slate-300 file:mr-2 file:px-2 file:py-1 file:rounded file:border-0 file:bg-cyan-600/30 file:text-cyan-100 file:text-xs"
              disabled={uploading}
            />
          </div>
          {uploading && (
            <div className="flex items-center gap-2 text-xs text-cyan-300">
              <Loader2 className="w-3 h-3 animate-spin" /> Uploading + embedding…
            </div>
          )}
        </div>
      </div>

      {/* Items list */}
      <div>
        <h2 className="text-sm font-medium text-white mb-2 flex items-center gap-2">
          <Shield className="w-4 h-4 text-cyan-400" />
          Items in scope "{activeScope}"
          <span className="text-xs text-slate-500 font-normal">
            ({items.length} {items.length === 1 ? 'item' : 'items'})
          </span>
        </h2>
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="w-5 h-5 animate-spin text-cyan-500" />
          </div>
        ) : items.length === 0 ? (
          <p className="text-xs text-slate-500 py-8 text-center">
            No items in this scope. Add a note or upload a file above.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/50 rounded-lg border border-slate-800/50 bg-slate-900/40">
            {items.map(p => (
              <div key={p.id} className="flex items-start gap-3 p-3">
                <div className="w-8 h-8 rounded bg-slate-800/70 flex items-center justify-center shrink-0">
                  {p.kind === 'note' ? <StickyNote className="w-4 h-4 text-emerald-300" /> :
                   p.kind === 'file' ? <FileText className="w-4 h-4 text-cyan-300" /> :
                   <Calendar className="w-4 h-4 text-purple-300" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm text-white truncate">{p.title}</p>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      p.status === 'indexed' ? 'bg-emerald-500/10 text-emerald-300' :
                      p.status === 'failed' ? 'bg-red-500/10 text-red-300' :
                      'bg-slate-500/10 text-slate-300'
                    }`}>
                      {p.status}
                    </span>
                  </div>
                  <div className="flex gap-3 text-[11px] text-slate-500 mt-0.5">
                    <span className="font-mono">{p.persona_scope}</span>
                    <span>{p.chunk_count} chunks</span>
                    <span>{(p.byte_size / 1024).toFixed(1)} KB</span>
                    {p.source && <span className="truncate">{p.source}</span>}
                  </div>
                </div>
                <button
                  onClick={() => deleteItem(p.id)}
                  className="text-slate-500 hover:text-red-400"
                  title="Delete"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
