'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  UserCircle2, Plus, Upload, FileText, Trash2, Shield, Lock, X, Eye, Pencil, RefreshCw,
  Loader2, StickyNote, Tag, Calendar, Mic, MicOff, CheckCircle2, AlertTriangle, Database,
  Info, ChevronDown, ChevronRight, Bot,
} from 'lucide-react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useIsAdmin } from '@/hooks/useToolConfig';

interface PersonaItem {
  id: string;
  persona_scope: string;
  kind: string;
  title: string;
  source: string | null;
  byte_size: number;
  chunk_count: number;
  status: string;
  last_error: string | null;
  embedding_model: string | null;
  has_content: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface PersonaItemFull extends PersonaItem {
  content: string | null;
}

type SaveResult = PersonaItem & { warning?: string };

interface StoreStatus {
  backend: string;
  ready: boolean;
  pgvector: boolean;
  embedding_model: string;
  semantic: boolean;
  error: string | null;
}

interface VoiceState {
  voice_id: string | null;
  voice_provider: string | null;
  voice_consent_at: string | null;
  has_clone: boolean;
  elevenlabs_configured: boolean;
}

const SCOPE_RE = /^[A-Za-z0-9:_\-.]+$/;
const UPLOAD_EXTS = ['.txt', '.md', '.pdf'];
const MAX_UPLOAD_MB = 10;

// server messages are already written for people, transport ones are not
function plain(msg: string): string {
  if (/failed to fetch|networkerror|network error|load failed/i.test(msg)) {
    return 'Could not reach the server. Check your connection and try again.';
  }
  if (/session expired|unauthenticated/i.test(msg)) return 'Your session has expired. Sign in again and retry.';
  if (/^server error \(5\d\d\)/i.test(msg)) {
    return 'Something went wrong on the server. Try again, and if it keeps failing tell an admin.';
  }
  if (/^server error \(413\)/i.test(msg)) return 'That is too large to upload.';
  return msg;
}

function errMsg(e: unknown, fallback: string): string {
  return plain(e instanceof Error && e.message ? e.message : fallback);
}

const HOWTO_KEY = 'persona.howto.collapsed';

function StatusPill({ p }: { p: PersonaItem }) {
  if (p.status === 'indexed') {
    return (
      <span
        title={`Indexed into ${p.chunk_count} ${p.chunk_count === 1 ? 'chunk' : 'chunks'}. Agents with Persona RAG can find it.`}
        className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300"
      >
        <CheckCircle2 className="w-3 h-3" /> ready
      </span>
    );
  }
  if (p.status === 'failed') {
    return (
      <span
        title={p.last_error || 'Indexing failed'}
        className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-300"
      >
        <AlertTriangle className="w-3 h-3" /> not searchable
      </span>
    );
  }
  return (
    <span title="Being split into chunks and embedded" className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-500/10 text-slate-300">
      <Loader2 className="w-3 h-3 animate-spin" /> indexing
    </span>
  );
}

function mergeScopes(...lists: string[][]): string[] {
  const out = ['self'];
  for (const list of lists) {
    for (const s of list) if (s && !out.includes(s)) out.push(s);
  }
  return out;
}

// a select must show its value even when the list does not have it yet
function withCurrent(list: string[], current: string): string[] {
  return current && !list.includes(current) ? [...list, current] : list;
}

const selectCls = 'px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white max-w-full';
const inputCls = 'w-full px-3 py-2 bg-slate-800/60 border border-slate-700/50 rounded text-sm text-white placeholder-slate-500';

export default function PersonaPage() {
  usePageTitle('Persona KB');
  const isAdmin = useIsAdmin();
  const [items, setItems] = useState<PersonaItem[]>([]);
  const [scopes, setScopes] = useState<string[]>(['self']);
  const [activeScope, setActiveScope] = useState<string>('self');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [store, setStore] = useState<StoreStatus | null>(null);
  const [showNote, setShowNote] = useState(false);
  const [noteTitle, setNoteTitle] = useState('');
  const [noteText, setNoteText] = useState('');
  const [noteScope, setNoteScope] = useState('self');
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadScope, setUploadScope] = useState('self');
  const [uploadTitle, setUploadTitle] = useState('');
  const [newScope, setNewScope] = useState('');
  const [openId, setOpenId] = useState<string | null>(null);
  const [openItem, setOpenItem] = useState<PersonaItemFull | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editText, setEditText] = useState('');
  const [editScope, setEditScope] = useState('self');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [voice, setVoice] = useState<VoiceState | null>(null);
  const [voiceName, setVoiceName] = useState('My meeting voice');
  const [voiceUploading, setVoiceUploading] = useState(false);
  const voiceFileRef = useRef<HTMLInputElement>(null);
  const [howtoOpen, setHowtoOpen] = useState(true);

  useEffect(() => {
    try { if (localStorage.getItem(HOWTO_KEY) === '1') setHowtoOpen(false); } catch { /* storage blocked */ }
  }, []);

  const toggleHowto = () => {
    const next = !howtoOpen;
    setHowtoOpen(next);
    try { localStorage.setItem(HOWTO_KEY, next ? '0' : '1'); } catch { /* storage blocked */ }
  };

  const agentHref = `/builder?tool=persona_rag&persona_scope=${encodeURIComponent(activeScope)}`;

  const openNoteForm = () => { startAction(); setShowNote(true); setNoteScope(activeScope || 'self'); };

  const startAction = () => { setErr(null); setNotice(null); };

  const load = useCallback(async (scope: string) => {
    setLoading(true);
    const [itemsR, scopesR, voiceR, storeR] = await Promise.all([
      apiFetch<PersonaItem[]>(`/api/persona/items?scope=${encodeURIComponent(scope)}`),
      apiFetch<string[]>('/api/persona/scopes'),
      apiFetch<VoiceState>('/api/persona/voice', { silent: true }),
      apiFetch<StoreStatus>('/api/persona/status', { silent: true }),
    ]);
    const firstErr = itemsR.error || scopesR.error;
    if (firstErr) setErr(`Could not load your persona items. ${plain(firstErr)}`);
    setItems(itemsR.data || []);
    setScopes(prev => mergeScopes(prev, scopesR.data || [], [scope]));
    setVoice(voiceR.data || null);
    setStore(storeR.data || null);
    setLoading(false);
  }, []);

  useEffect(() => {
    load(activeScope);
    setUploadScope(activeScope);
    if (!showNote) setNoteScope(activeScope);
  }, [activeScope]);

  const reload = () => load(activeScope);

  const showSaved = (r: SaveResult | null) => {
    if (r?.warning) setNotice(r.warning);
  };

  const goToScope = async (scope: string) => {
    setScopes(prev => mergeScopes(prev, [scope]));
    if (scope !== activeScope) setActiveScope(scope);
    else await reload();
  };

  const uploadVoice = async () => {
    startAction();
    const file = voiceFileRef.current?.files?.[0];
    if (!file) { setErr('Select a clip first'); return; }
    setVoiceUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('name', voiceName || 'My meeting voice');
      await apiFetch('/api/persona/voice/upload', { method: 'POST', body: fd });
      await reload();
    } catch (e: unknown) {
      setErr(errMsg(e, 'voice upload failed'));
    }
    if (voiceFileRef.current) voiceFileRef.current.value = '';
    setVoiceUploading(false);
  };

  const giveConsent = async () => {
    startAction();
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
      await reload();
    } catch (e: unknown) {
      setErr(errMsg(e, 'consent failed'));
    }
  };

  const revokeVoice = async () => {
    startAction();
    if (!confirm('Revoke consent AND delete the cloned voice from ElevenLabs?')) return;
    try {
      await apiFetch('/api/persona/voice/revoke', { method: 'POST', body: '{}' });
      await reload();
    } catch (e: unknown) {
      setErr(errMsg(e, 'revoke failed'));
    }
  };

  const addNote = async () => {
    startAction();
    if (!noteText.trim()) return;
    setSaving(true);
    try {
      const r = await apiFetch<SaveResult>('/api/persona/notes', {
        method: 'POST',
        body: JSON.stringify({
          title: noteTitle.trim() || 'Note',
          text: noteText,
          persona_scope: noteScope,
        }),
      });
      showSaved(r.data);
      setNoteTitle(''); setNoteText(''); setShowNote(false);
      await goToScope(noteScope);
    } catch (e: unknown) {
      setErr(errMsg(e, 'save failed'));
    }
    setSaving(false);
  };

  const resetPicker = () => {
    if (fileRef.current) fileRef.current.value = '';
    setUploadFile(null);
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    startAction();
    const file = e.target.files?.[0] || null;
    if (!file) { setUploadFile(null); return; }
    const lower = file.name.toLowerCase();
    if (!UPLOAD_EXTS.some(x => lower.endsWith(x))) {
      setErr(`${file.name} is not supported. Upload a .txt, .md or .pdf file.`);
      resetPicker();
      return;
    }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
      setErr(`${file.name} is ${(file.size / 1024 / 1024).toFixed(1)} MB, the limit is ${MAX_UPLOAD_MB} MB.`);
      resetPicker();
      return;
    }
    setUploadFile(file);
  };

  const upload = async () => {
    startAction();
    if (!uploadFile) { setErr('Choose a file first'); return; }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', uploadFile);
      fd.append('title', uploadTitle.trim() || uploadFile.name);
      fd.append('persona_scope', uploadScope);
      const r = await apiFetch<SaveResult>('/api/persona/upload', { method: 'POST', body: fd });
      showSaved(r.data);
      setUploadTitle('');
      await goToScope(uploadScope);
    } catch (e: unknown) {
      setErr(errMsg(e, 'upload failed'));
    }
    resetPicker();
    setUploading(false);
  };

  const deleteItem = async (id: string) => {
    startAction();
    if (!confirm('Delete this item and its vectors from the persona KB?')) return;
    setBusyId(id);
    try {
      await apiFetch(`/api/persona/items/${id}`, { method: 'DELETE' });
      if (openId === id) { setOpenId(null); setOpenItem(null); setEditing(false); }
      await reload();
    } catch (e: unknown) {
      setErr(errMsg(e, 'delete failed'));
    }
    setBusyId(null);
  };

  const reindex = async (id: string) => {
    startAction();
    setBusyId(id);
    try {
      const r = await apiFetch<SaveResult>(`/api/persona/items/${id}/reindex`, { method: 'POST', body: '{}' });
      showSaved(r.data);
      await reload();
    } catch (e: unknown) {
      setErr(errMsg(e, 're-index failed'));
    }
    setBusyId(null);
  };

  const toggleOpen = async (id: string) => {
    startAction();
    setEditing(false);
    if (openId === id) { setOpenId(null); setOpenItem(null); return; }
    setOpenId(id);
    setOpenItem(null);
    const r = await apiFetch<PersonaItemFull>(`/api/persona/items/${id}`);
    if (r.error) { setErr(`Could not open the item. ${plain(r.error)}`); setOpenId(null); return; }
    setOpenItem(r.data);
  };

  const startEdit = () => {
    if (!openItem) return;
    setEditTitle(openItem.title);
    setEditText(openItem.content || '');
    setEditScope(openItem.persona_scope);
    setEditing(true);
  };

  const saveEdit = async () => {
    startAction();
    if (!openItem) return;
    if (!editTitle.trim()) { setErr('Title cannot be empty'); return; }
    const body: Record<string, string> = { title: editTitle.trim(), persona_scope: editScope };
    if (openItem.kind !== 'file') {
      if (!editText.trim()) { setErr('Text cannot be empty'); return; }
      body.text = editText;
    }
    setBusyId(openItem.id);
    try {
      const r = await apiFetch<SaveResult>(`/api/persona/items/${openItem.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      showSaved(r.data);
      setEditing(false);
      const full = await apiFetch<PersonaItemFull>(`/api/persona/items/${openItem.id}`);
      if (full.data) setOpenItem(full.data);
      await goToScope(editScope);
    } catch (e: unknown) {
      setErr(errMsg(e, 'save failed'));
    }
    setBusyId(null);
  };

  const addScope = () => {
    startAction();
    const v = newScope.trim();
    if (!v) return;
    if (!SCOPE_RE.test(v) || v.length > 80) {
      setErr('Scope must be letters, digits, dash, colon, underscore or dot, up to 80 characters');
      return;
    }
    setScopes(prev => mergeScopes(prev, [v]));
    setNewScope('');
    setActiveScope(v);
  };

  return (
    <div className="space-y-6 max-w-5xl min-w-0">
      <div>
        <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
          <UserCircle2 className="w-6 h-6 text-cyan-400" />
          Persona KB
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Notes and files about you that your agents can use to answer as you. Only you can retrieve them.
        </p>
        <div className="mt-2 flex items-start gap-1.5 text-xs text-slate-500">
          <Lock className="w-3 h-3 mt-0.5 shrink-0" />
          <span>Every search is filtered on your tenant, on you as the owner and on the persona scope. No other user can read your items.</span>
        </div>
        {store && (
          <div className="mt-1 flex items-start gap-1.5 text-xs text-slate-500" data-testid="persona-store-status">
            <Database className="w-3 h-3 mt-0.5 shrink-0" />
            {store.ready ? (
              <span>
                Stored in {store.pgvector ? 'Postgres with pgvector' : 'Postgres (pgvector extension missing, search is slower)'}.
                {' '}Embeddings: {store.semantic
                  ? <code className="text-slate-400">{store.embedding_model}</code>
                  : <>built-in keyword matching{isAdmin ? ', add an OpenAI key in Tool Configuration for semantic search' : ''}</>}.
              </span>
            ) : (
              <span className="text-amber-300">
                The persona store is not ready: {store.error || 'the persona_chunks table is missing, the database migrations have not run'}.
              </span>
            )}
          </div>
        )}
      </div>

      <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5" data-testid="persona-howto">
        <button
          onClick={toggleHowto}
          aria-expanded={howtoOpen}
          className="w-full flex items-center gap-2 px-4 py-2.5 text-left text-sm text-cyan-100"
        >
          <Info className="w-4 h-4 text-cyan-300 shrink-0" />
          <span className="flex-1 font-medium">How this works</span>
          {howtoOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
        {howtoOpen && (
          <div className="px-4 pb-4 grid gap-3 sm:grid-cols-3 text-xs text-slate-300">
            <div className="space-y-1">
              <p className="font-medium text-white">1. Add what your agent should know</p>
              <p>Write a note or upload a .txt, .md or .pdf. Each item goes into a <strong>scope</strong>, a label that groups items, such as <code className="text-cyan-300">self</code>, <code className="text-cyan-300">client:acme</code> or <code className="text-cyan-300">project:q2</code>. Use <code className="text-cyan-300">self</code> for facts about you.</p>
            </div>
            <div className="space-y-1">
              <p className="font-medium text-white">2. It stays yours</p>
              <p>Only agents running as you can read your items, and only through the Persona RAG tool. Other users, admins included, cannot retrieve them, and generic knowledge searches never return them. In a meeting the bot can read only the scopes you authorized for that meeting.</p>
            </div>
            <div className="space-y-1">
              <p className="font-medium text-white">3. Use it in an agent</p>
              <p>Click <strong>Use in an agent</strong> below. It opens the builder with Persona RAG added for the current scope. Run that agent and ask it about yourself.</p>
            </div>
          </div>
        )}
      </div>

      {err && (
        <div role="alert" data-testid="persona-error" className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
          <span className="flex-1 min-w-0 break-words">{err}</span>
          <button onClick={() => setErr(null)} aria-label="Dismiss error" className="shrink-0 hover:text-red-100">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      {notice && (
        <div role="status" data-testid="persona-notice" className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="flex-1 min-w-0 break-words">{notice.replace(/\.$/, '')}. Fix the cause, then use Re-index on the item.</span>
          <button onClick={() => setNotice(null)} aria-label="Dismiss notice" className="shrink-0 hover:text-amber-50">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Voice clone panel */}
      <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
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

        {voice && !voice.elevenlabs_configured && (
          isAdmin ? (
            <div className="text-xs text-amber-300/80 bg-amber-500/5 border border-amber-500/30 rounded p-2 break-words">
              Voice cloning needs an ElevenLabs key.{' '}
              <Link href="/admin/tool-config#ELEVENLABS_API_KEY" className="underline text-amber-200 hover:text-amber-100" data-testid="persona-voice-configure">
                Add ELEVENLABS_API_KEY in Tool Configuration
              </Link>
              , it applies within 30 seconds with no restart.
            </div>
          ) : (
            <p className="text-xs text-slate-400">
              Voice cloning is not enabled on this server. Ask an admin if you need it.
            </p>
          )
        )}

        {voice?.elevenlabs_configured && !voice?.voice_id && (
          <>
            <p className="text-xs text-slate-400">
              Upload a <strong>30-120 second WAV/MP3</strong> of yourself speaking
              naturally, ideally reading a paragraph at conversational pace in a
              quiet room. ElevenLabs clones the voice and we store only the resulting
              voice_id here. The bot CANNOT use the clone until you separately
              record consent below.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={voiceName}
                onChange={e => setVoiceName(e.target.value)}
                className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white w-full sm:w-48"
                placeholder="Voice name"
              />
              <input
                ref={voiceFileRef}
                type="file"
                accept="audio/*"
                className="text-xs text-slate-300 max-w-full file:mr-2 file:px-2 file:py-1 file:rounded file:border-0 file:bg-purple-600/30 file:text-purple-100"
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
              <em>By clicking &quot;I consent&quot;</em>: I authorize Abenix to use my
              cloned voice when the Meeting Representative agent speaks on my
              behalf in meetings I have explicitly authorized. I understand I can
              revoke this consent at any time, and revocation also deletes the voice
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
          <div className="text-xs text-slate-400 break-words">
            voice_id: <code className="text-purple-300">{voice.voice_id?.slice(0, 12)}…</code>{' '}
            · provider: <code className="text-purple-300">{voice.voice_provider}</code>{' '}
            · consented: {voice.voice_consent_at ? new Date(voice.voice_consent_at).toLocaleString() : '—'}
          </div>
        )}
      </div>

      {/* Scope selector */}
      <div className="flex flex-wrap items-center gap-2" data-testid="persona-scopes">
        <span className="text-xs text-slate-500 mr-2">Scope:</span>
        {scopes.map(s => (
          <button
            key={s}
            onClick={() => { startAction(); setActiveScope(s); }}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs border max-w-full break-all ${
              activeScope === s
                ? 'bg-cyan-500/10 border-cyan-500/40 text-cyan-200'
                : 'border-slate-700/50 text-slate-400 hover:text-slate-200'
            }`}
          >
            <Tag className="w-3 h-3 shrink-0" />
            {s}
          </button>
        ))}
        <div className="flex items-center gap-1 w-full sm:w-auto sm:ml-2">
          <input
            value={newScope}
            onChange={e => setNewScope(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addScope()}
            placeholder="new scope (e.g. client:acme)"
            aria-label="New scope"
            className="px-2 py-1 bg-slate-800/60 border border-slate-700/50 rounded text-xs text-white flex-1 sm:flex-none sm:w-52 min-w-0"
          />
          <button onClick={addScope} aria-label="Add scope" className="px-2 py-1 text-xs rounded border border-slate-700/50 text-slate-300">
            <Plus className="w-3 h-3" />
          </button>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {/* Add note */}
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3 min-w-0">
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
                className={inputCls}
              />
              <textarea
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="Anything you want your bot to know: context, preferences, facts, stance on topics."
                rows={6}
                className={`${inputCls} resize-y`}
              />
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={noteScope}
                  onChange={e => setNoteScope(e.target.value)}
                  aria-label="Note scope"
                  className={selectCls}
                >
                  {withCurrent(scopes, noteScope).map(s => <option key={s} value={s}>{s}</option>)}
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
              onClick={openNoteForm}
              className="w-full px-3 py-2 text-sm rounded border border-dashed border-slate-700 text-slate-400 hover:border-emerald-500/40 hover:text-emerald-300"
            >
              + Add note
            </button>
          )}
        </div>

        {/* Upload file */}
        <div className="rounded-lg border border-slate-800/50 bg-slate-900/40 p-4 space-y-3 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Upload className="w-4 h-4 text-cyan-400" />
            <h3 className="text-sm font-medium text-white">Upload file</h3>
            <span className="text-[10px] text-slate-500">.txt, .md or .pdf, up to {MAX_UPLOAD_MB} MB</span>
          </div>
          <input
            value={uploadTitle}
            onChange={e => setUploadTitle(e.target.value)}
            placeholder="Title (optional — defaults to filename)"
            className={inputCls}
          />
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={uploadScope}
              onChange={e => setUploadScope(e.target.value)}
              aria-label="Upload scope"
              className={selectCls}
            >
              {withCurrent(scopes, uploadScope).map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.pdf"
              onChange={onPick}
              aria-label="File to upload"
              className="text-xs text-slate-300 max-w-full min-w-0 file:mr-2 file:px-2 file:py-1 file:rounded file:border-0 file:bg-cyan-600/30 file:text-cyan-100 file:text-xs"
              disabled={uploading}
            />
            <button
              onClick={upload}
              disabled={uploading || !uploadFile}
              className="px-3 py-1.5 text-xs rounded bg-cyan-600/30 border border-cyan-500/40 text-cyan-100 hover:bg-cyan-600/50 disabled:opacity-50"
            >
              Upload
            </button>
          </div>
          {uploading && (
            <div className="flex items-center gap-2 text-xs text-cyan-300">
              <Loader2 className="w-3 h-3 animate-spin" /> Uploading + embedding…
            </div>
          )}
        </div>
      </div>

      {/* Items list */}
      <div className="min-w-0">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-medium text-white flex flex-wrap items-center gap-2 min-w-0">
            <Shield className="w-4 h-4 text-cyan-400" />
            <span className="break-all">Items in scope &quot;{activeScope}&quot;</span>
            <span className="text-xs text-slate-500 font-normal">
              ({items.length} {items.length === 1 ? 'item' : 'items'})
            </span>
          </h2>
          <Link
            href={agentHref}
            data-testid="persona-use-in-agent"
            title={`Open the builder with Persona RAG reading scope ${activeScope}`}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs text-cyan-300 hover:text-white border border-cyan-500/30 hover:border-cyan-400 rounded-lg"
          >
            <Bot className="w-3.5 h-3.5" /> Use in an agent
          </Link>
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="w-5 h-5 animate-spin text-cyan-500" />
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-700/70 py-8 px-4 text-center space-y-3" data-testid="persona-empty">
            <p className="text-sm text-slate-300">Nothing in scope &quot;{activeScope}&quot; yet.</p>
            <p className="text-xs text-slate-500 max-w-md mx-auto">
              Start with a note about yourself, for example your role, how you like to be
              addressed and what you are working on. Then ask an agent that has Persona RAG
              something like &quot;What am I working on?&quot;.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              <button
                onClick={openNoteForm}
                className="px-3 py-1.5 text-xs rounded bg-emerald-600/30 border border-emerald-500/40 text-emerald-100 hover:bg-emerald-600/50"
              >
                + Add a note
              </button>
              <Link
                href={agentHref}
                className="px-3 py-1.5 text-xs rounded border border-cyan-500/30 text-cyan-300 hover:text-white"
              >
                Use in an agent
              </Link>
            </div>
          </div>
        ) : (
          <div className="divide-y divide-slate-800/50 rounded-lg border border-slate-800/50 bg-slate-900/40">
            {items.map(p => (
              <div key={p.id} className="p-3 min-w-0" data-testid="persona-item">
                <div className="flex items-start gap-3">
                  <div className="hidden sm:flex w-8 h-8 rounded bg-slate-800/70 items-center justify-center shrink-0">
                    {p.kind === 'note' ? <StickyNote className="w-4 h-4 text-emerald-300" /> :
                     p.kind === 'file' ? <FileText className="w-4 h-4 text-cyan-300" /> :
                     <Calendar className="w-4 h-4 text-purple-300" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <button
                        onClick={() => toggleOpen(p.id)}
                        className="text-sm text-white text-left break-words min-w-0 hover:underline"
                      >
                        {p.title}
                      </button>
                      <StatusPill p={p} />
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500 mt-0.5">
                      <span className="font-mono break-all">{p.persona_scope}</span>
                      <span>{p.chunk_count} {p.chunk_count === 1 ? 'chunk' : 'chunks'}</span>
                      <span>{(p.byte_size / 1024).toFixed(1)} KB</span>
                      {p.source && p.source !== 'note' && <span className="break-all">{p.source}</span>}
                    </div>
                    {p.status === 'failed' && (
                      <div className="mt-1 flex flex-wrap items-center gap-2" data-testid="persona-item-error">
                        <p className="text-[11px] text-red-300/90 break-words min-w-0">
                          Agents cannot find this yet: {(p.last_error || 'indexing did not finish').replace(/\.$/, '')}.
                        </p>
                        <button
                          onClick={() => reindex(p.id)}
                          disabled={busyId === p.id}
                          className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded border border-amber-500/40 text-amber-200 hover:bg-amber-500/10 disabled:opacity-50"
                        >
                          <RefreshCw className={`w-3 h-3 ${busyId === p.id ? 'animate-spin' : ''}`} /> Re-index
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => toggleOpen(p.id)}
                      className="text-slate-500 hover:text-cyan-300"
                      title={openId === p.id ? 'Close' : 'View'}
                      aria-label={openId === p.id ? 'Close' : 'View'}
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => reindex(p.id)}
                      disabled={busyId === p.id}
                      className={`hover:text-cyan-300 disabled:opacity-50 ${p.status === 'failed' ? 'text-amber-300' : 'text-slate-500'}`}
                      title="Re-index"
                      aria-label="Re-index"
                    >
                      <RefreshCw className={`w-4 h-4 ${busyId === p.id ? 'animate-spin' : ''}`} />
                    </button>
                    <button
                      onClick={() => deleteItem(p.id)}
                      disabled={busyId === p.id}
                      className="text-slate-500 hover:text-red-400 disabled:opacity-50"
                      title="Delete"
                      aria-label="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                {openId === p.id && (
                  <div className="mt-3 rounded border border-slate-800/70 bg-slate-950/40 p-3 space-y-2">
                    {!openItem ? (
                      <div className="flex items-center gap-2 text-xs text-slate-400">
                        <Loader2 className="w-3 h-3 animate-spin" /> Loading…
                      </div>
                    ) : editing ? (
                      <>
                        <input
                          value={editTitle}
                          onChange={e => setEditTitle(e.target.value)}
                          placeholder="Title"
                          aria-label="Edit title"
                          className={inputCls}
                        />
                        {openItem.kind !== 'file' ? (
                          <textarea
                            value={editText}
                            onChange={e => setEditText(e.target.value)}
                            rows={8}
                            aria-label="Edit text"
                            className={`${inputCls} resize-y`}
                          />
                        ) : (
                          <p className="text-[11px] text-slate-500">The text of an uploaded file cannot be edited. Upload it again to change it.</p>
                        )}
                        <div className="flex flex-wrap items-center gap-2">
                          <select
                            value={editScope}
                            onChange={e => setEditScope(e.target.value)}
                            aria-label="Edit scope"
                            className={selectCls}
                          >
                            {withCurrent(scopes, editScope).map(s => <option key={s} value={s}>{s}</option>)}
                          </select>
                          <button
                            onClick={saveEdit}
                            disabled={busyId === openItem.id}
                            className="px-3 py-1.5 text-xs rounded bg-emerald-600/30 border border-emerald-500/40 text-emerald-100 hover:bg-emerald-600/50 disabled:opacity-50"
                          >
                            {busyId === openItem.id ? 'Saving…' : 'Save and re-index'}
                          </button>
                          <button
                            onClick={() => setEditing(false)}
                            className="px-3 py-1.5 text-xs rounded border border-slate-700/50 text-slate-400"
                          >
                            Cancel
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        {openItem.content ? (
                          <pre className="whitespace-pre-wrap break-words text-xs text-slate-300 max-h-80 overflow-auto font-sans">
                            {openItem.content}
                          </pre>
                        ) : (
                          <p className="text-xs text-slate-500">
                            The original text of this item was not kept. Delete it and add it again to edit it.
                          </p>
                        )}
                        <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                          {openItem.embedding_model && <span>Embedded with {openItem.embedding_model}</span>}
                          {openItem.updated_at && <span>Updated {new Date(openItem.updated_at).toLocaleString()}</span>}
                          {openItem.has_content && (
                            <button
                              onClick={startEdit}
                              className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded border border-slate-700/50 text-slate-300 hover:text-white"
                            >
                              <Pencil className="w-3 h-3" /> Edit
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
