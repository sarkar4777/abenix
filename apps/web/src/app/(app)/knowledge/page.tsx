'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft,
  Database,
  FileText,
  Loader2,
  Plus,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { KnowledgeSkeleton } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { useApi } from '@/hooks/useApi';
import { apiFetch, API_URL } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';

interface KnowledgeBase {
  id: string;
  name: string;
  description: string;
  status: string;
  doc_count: number;
  chunk_count: number;
  total_size: number;
  created_at: string | null;
  updated_at: string | null;
}

interface KBDetail {
  id: string;
  name: string;
  description: string;
  status: string;
  doc_count: number;
  embedding_model: string;
  chunk_size: number;
  chunk_overlap: number;
  documents: DocumentInfo[];
  created_at: string | null;
}

interface DocumentInfo {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  chunk_count: number;
  status: string;
  created_at: string | null;
}

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : {};
}

function getAuthHeadersRaw(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusColor(status: string): string {
  if (status === 'ready') return 'text-emerald-400 bg-emerald-500/10';
  if (status === 'processing') return 'text-amber-400 bg-amber-500/10';
  return 'text-red-400 bg-red-500/10';
}

function CreateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (kb: KnowledgeBase) => void;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');

  const reset = () => { setName(''); setDescription(''); setErr(''); };

  const submit = async () => {
    if (!name.trim()) { setErr('Name is required'); return; }
    setSubmitting(true);
    setErr('');
    try {
      const res = await fetch(`${API_URL}/api/knowledge-bases`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ name: name.trim(), description: description.trim() }),
      });
      const json = await res.json();
      if (json.error) { setErr(json.error.message); return; }
      onCreated(json.data);
      reset();
      onClose();
    } catch {
      setErr('Failed to create');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ResponsiveModal open={open} onClose={() => { reset(); onClose(); }} title="New Knowledge Base" maxWidth="max-w-md">
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Product Documentation"
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What kind of documents will this contain?"
            rows={3}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500"
          />
        </div>
        {err && <p className="text-xs text-red-400">{err}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={() => { reset(); onClose(); }} className="px-4 py-2 text-sm text-slate-400 hover:text-white transition-colors">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Create
          </button>
        </div>
      </div>
    </ResponsiveModal>
  );
}

function DropZone({
  kbId,
  onUploaded,
}: {
  kbId: string;
  onUploaded: (doc: DocumentInfo) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = async (file: File) => {
    setUploading(true);
    setUploadError('');
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API_URL}/api/knowledge-bases/${kbId}/upload`, {
        method: 'POST',
        headers: getAuthHeadersRaw(),
        body: form,
      });
      const json = await res.json();
      if (json.error) {
        setUploadError(json.error.message);
        return;
      }
      onUploaded(json.data);
    } catch {
      setUploadError('Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) upload(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) upload(file);
    e.target.value = '';
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
        dragging
          ? 'border-cyan-400 bg-cyan-500/5'
          : 'border-slate-700/50 hover:border-slate-600 bg-slate-800/20'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt,.csv,.md,.json"
        onChange={handleFileChange}
        className="hidden"
      />
      {uploading ? (
        <div className="flex flex-col items-center gap-2">
          <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
          <p className="text-xs text-slate-400">Uploading...</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <Upload className={`w-6 h-6 ${dragging ? 'text-cyan-400' : 'text-slate-600'}`} />
          <p className="text-xs text-slate-400">
            Drop files here or click to browse
          </p>
          <p className="text-[10px] text-slate-600">
            PDF, DOCX, TXT, CSV, MD, JSON (max 50 MB)
          </p>
        </div>
      )}
      {uploadError && <p className="text-xs text-red-400 mt-2">{uploadError}</p>}
    </div>
  );
}

function KBDetailView({
  kb,
  onBack,
  onDeleted,
}: {
  kb: KBDetail;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const [docs, setDocs] = useState<DocumentInfo[]>(kb.documents || []);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deletingKB, setDeletingKB] = useState(false);
  const [confirmDeleteKB, setConfirmDeleteKB] = useState(false);

  const pollInterval = useRef<ReturnType<typeof setInterval>>();

  const hasProcessing = docs.some((d) => d.status === 'processing');

  useEffect(() => {
    if (!hasProcessing) {
      if (pollInterval.current) clearInterval(pollInterval.current);
      return;
    }

    pollInterval.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/knowledge-bases/${kb.id}/documents`, {
          headers: getAuthHeaders(),
        });
        const json = await res.json();
        if (json.data) setDocs(json.data);
      } catch {
        // silent
      }
    }, 3000);

    return () => {
      if (pollInterval.current) clearInterval(pollInterval.current);
    };
  }, [hasProcessing, kb.id]);

  const handleUploaded = (doc: DocumentInfo) => {
    setDocs((prev) => [doc, ...prev]);
  };

  const deleteDoc = async (docId: string) => {
    setDeleting(docId);
    try {
      await fetch(`${API_URL}/api/knowledge-bases/${kb.id}/documents/${docId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      setDocs((prev) => prev.filter((d) => d.id !== docId));
      toastSuccess('Document deleted');
    } catch {
      toastError('Failed to delete document');
    } finally {
      setDeleting(null);
    }
  };

  const deleteKB = async () => {
    setDeletingKB(true);
    try {
      await fetch(`${API_URL}/api/knowledge-bases/${kb.id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      onDeleted();
      toastSuccess('Knowledge base deleted');
    } catch {
      toastError('Failed to delete knowledge base');
    } finally {
      setDeletingKB(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="space-y-6"
    >
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
      </div>

      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">{kb.name}</h1>
          {kb.description && (
            <p className="text-sm text-slate-500 mt-1">{kb.description}</p>
          )}
          <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
            <span className={`px-2 py-0.5 rounded-full ${statusColor(kb.status)}`}>
              {kb.status}
            </span>
            <span>{docs.length} documents</span>
            <span>Chunk size: {kb.chunk_size}</span>
          </div>
        </div>
        <button
          onClick={() => setConfirmDeleteKB(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 hover:text-red-300 border border-red-500/20 hover:border-red-500/40 rounded-lg transition-colors"
        >
          <Trash2 className="w-3 h-3" />
          Delete KB
        </button>
      </div>

      <DropZone kbId={kb.id} onUploaded={handleUploaded} />

      <div>
        <h3 className="text-sm font-medium text-slate-300 mb-3">
          Documents ({docs.length})
        </h3>
        {docs.length === 0 && (
          <div className="text-center py-8">
            <FileText className="w-8 h-8 text-slate-700 mx-auto mb-2" />
            <p className="text-sm text-slate-500">No documents yet</p>
            <p className="text-xs text-slate-600">Upload files above to get started</p>
          </div>
        )}
        <div className="space-y-2">
          {docs.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-3 p-3 bg-slate-800/30 border border-slate-700/50 rounded-lg group"
            >
              <div className="w-8 h-8 rounded-md bg-slate-700/50 flex items-center justify-center shrink-0">
                <FileText className="w-4 h-4 text-slate-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{doc.filename}</p>
                <div className="flex items-center gap-3 text-[10px] text-slate-500">
                  <span>{doc.file_type.toUpperCase()}</span>
                  <span>{formatSize(doc.file_size)}</span>
                  {doc.chunk_count > 0 && <span>{doc.chunk_count} chunks</span>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] px-2 py-0.5 rounded-full ${statusColor(doc.status)}`}>
                  {doc.status === 'processing' && (
                    <Loader2 className="w-2.5 h-2.5 animate-spin inline mr-1" />
                  )}
                  {doc.status}
                </span>
                <button
                  onClick={() => deleteDoc(doc.id)}
                  disabled={deleting === doc.id}
                  className="text-slate-500 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 disabled:opacity-50"
                >
                  {deleting === doc.id ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="w-3.5 h-3.5" />
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
      <ConfirmModal
        open={confirmDeleteKB}
        onClose={() => setConfirmDeleteKB(false)}
        onConfirm={deleteKB}
        title="Delete Knowledge Base"
        description={`Are you sure you want to delete "${kb.name}"? All documents and embeddings will be permanently removed.`}
        confirmLabel="Delete"
        loading={deletingKB}
      />
    </motion.div>
  );
}

export default function KnowledgePage() {
  usePageTitle('Knowledge Bases');
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedKB, setSelectedKB] = useState<KBDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('newest');
  const [page, setPage] = useState(0);
  const LIMIT = 20;

  const apiUrl = `/api/knowledge-bases?search=${encodeURIComponent(search)}&status=${encodeURIComponent(statusFilter)}&sort=${sortBy}&limit=${LIMIT}&offset=${page * LIMIT}`;
  const { data: kbs, isLoading: loading, meta, mutate: mutateKBs } =
    useApi<KnowledgeBase[]>(apiUrl);

  const total = (meta?.total as number) || (kbs ?? []).length;

  const openDetail = async (kbId: string) => {
    setLoadingDetail(true);
    try {
      const res = await apiFetch<KBDetail>(`/api/knowledge-bases/${kbId}`);
      if (res.data) setSelectedKB(res.data);
    } catch {
      // silent
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleCreated = () => {
    mutateKBs();
  };

  const handleKBDeleted = () => {
    setSelectedKB(null);
    mutateKBs();
  };

  if (loading) {
    return <KnowledgeSkeleton />;
  }

  if (selectedKB) {
    return (
      <div className="max-w-[900px]">
        <KBDetailView
          kb={selectedKB}
          onBack={() => setSelectedKB(null)}
          onDeleted={handleKBDeleted}
        />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Knowledge Bases</h1>
          <p className="text-sm text-slate-500 mt-1">
            Manage RAG data sources for your agents.{' '}
            <a href="/knowledge/projects" className="text-emerald-400 hover:text-emerald-300">
              Group them into Projects →
            </a>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <a
            href="/knowledge/projects"
            className="hidden sm:inline-flex items-center gap-2 px-3 py-2 border border-slate-700 hover:border-slate-600 text-slate-200 text-sm font-medium rounded-lg transition-colors"
          >
            Projects
          </a>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
          >
            <Plus className="w-4 h-4" />
            New Knowledge Base
          </button>
        </div>
      </div>

      {/* Search & Filters */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search knowledge bases..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full pl-10 pr-4 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}
          className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
        >
          <option value="">All Status</option>
          <option value="ready">Ready</option>
          <option value="processing">Processing</option>
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:border-cyan-500 focus:outline-none"
        >
          <option value="newest">Newest First</option>
          <option value="oldest">Oldest First</option>
          <option value="name">Name A-Z</option>
        </select>
      </div>

      {(kbs ?? []).length === 0 && !loading && (
        <EmptyState
          icon={Database}
          title="No knowledge bases yet"
          description="Upload documents to get started with RAG-powered agents."
          actionLabel="New Knowledge Base"
          onAction={() => setModalOpen(true)}
        />
      )}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <AnimatePresence>
          {(kbs ?? []).map((kb) => (
            <motion.div
              key={kb.id}
              layout
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              onClick={() => openDetail(kb.id)}
              className="relative bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-colors cursor-pointer group"
            >
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(`Delete "${kb.name}"? All documents will be removed.`)) {
                    apiFetch(`/api/knowledge-bases/${kb.id}`, { method: 'DELETE' }).then(() => mutateKBs());
                  }
                }}
                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 p-1.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all"
                aria-label="Delete knowledge base"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
              <div className="flex items-start justify-between mb-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center">
                  <Database className="w-5 h-5 text-emerald-400" />
                </div>
                <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor(kb.status)}`}>
                  {kb.status === 'processing' && (
                    <Loader2 className="w-2.5 h-2.5 animate-spin inline mr-1" />
                  )}
                  {kb.status}
                </span>
              </div>
              <h3 className="text-sm font-semibold text-white mb-2">{kb.name}</h3>
              <div className="space-y-1.5 text-xs text-slate-500">
                <div className="flex items-center gap-2">
                  <FileText className="w-3 h-3" /> {kb.doc_count} documents
                </div>
                <div className="flex items-center gap-2">
                  <Database className="w-3 h-3" /> {(kb.chunk_count || 0).toLocaleString()} chunks
                </div>
                {kb.total_size > 0 && (
                  <div className="flex items-center gap-2">
                    <Upload className="w-3 h-3" /> {formatSize(kb.total_size)}
                  </div>
                )}
              </div>
              {kb.status === 'ready' && (
                <button
                  onClick={(e) => { e.stopPropagation(); window.location.href = `/knowledge/${kb.id}/engine`; }}
                  className="mt-3 w-full py-1.5 text-[10px] text-emerald-400 bg-emerald-500/5 border border-emerald-500/20 rounded-lg hover:bg-emerald-500/10 transition-colors flex items-center justify-center gap-1.5"
                >
                  <Database className="w-3 h-3" />
                  Knowledge Engine
                </button>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Pagination */}
      {total > LIMIT && (
        <div className="flex items-center justify-between mt-6">
          <p className="text-xs text-slate-500">
            Showing {page * LIMIT + 1}&ndash;{Math.min((page + 1) * LIMIT, total)} of {total} knowledge bases
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={(page + 1) * LIMIT >= total}
              className="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-xs text-slate-300 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {loadingDetail && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 backdrop-blur-sm">
          <Loader2 className="w-8 h-8 text-cyan-500 animate-spin" />
        </div>
      )}

      <CreateModal open={modalOpen} onClose={() => setModalOpen(false)} onCreated={handleCreated} />
    </motion.div>
  );
}
