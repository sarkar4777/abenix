'use client';

import { useEffect, useRef, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft,
  Bot,
  Database,
  FileText,
  FolderOpen,
  Loader2,
  Lock,
  Plus,
  Search,
  Share2,
  Trash2,
  Upload,
} from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import ResourceShareDialog from '@/components/share/ResourceShareDialog';
import DocumentAccessModal from '@/components/knowledge/DocumentAccessModal';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { KnowledgeSkeleton } from '@/components/ui/Skeleton';
import EmptyState from '@/components/ui/EmptyState';
import DeleteWithDependents from '@/components/ui/DeleteWithDependents';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { useApi } from '@/hooks/useApi';
import { apiFetch, API_URL } from '@/lib/api-client';
import { usePageTitle } from '@/hooks/usePageTitle';
import OwnerBadge from '@/components/OwnerBadge';

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
  owner_name?: string | null;
  ownership?: 'mine' | 'shared' | 'platform' | null;
  can_edit?: boolean | null;
  can_manage?: boolean;
}

interface KBDetail {
  can_edit?: boolean | null;
  can_manage?: boolean;
  owner_name?: string | null;
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
  error_message?: string | null;
  version_number?: number;
  is_current?: boolean;
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

const VISIBILITY_HELP: Record<string, string> = {
  project: 'Members of the project can read it.',
  tenant: 'Everyone in your organisation can read it.',
  private: 'Only you, admins and people you share it with.',
};

function CreateModal({
  open,
  onClose,
  onCreated,
  initialProject = '',
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (kb: KnowledgeBase) => void;
  initialProject?: string;
}) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [projectId, setProjectId] = useState(initialProject);
  const [visibility, setVisibility] = useState('project');
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState('');
  const { data: projects } = useApi<{ id: string; name: string }[]>(open ? '/api/knowledge-projects?limit=100' : null);

  useEffect(() => { if (open) setProjectId(initialProject); }, [open, initialProject]);

  const reset = () => { setName(''); setDescription(''); setVisibility('project'); setErr(''); };

  const submit = async () => {
    if (!name.trim()) { setErr('Name is required'); return; }
    setSubmitting(true);
    setErr('');
    try {
      const res = await fetch(`${API_URL}/api/knowledge-bases`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          project_id: projectId || undefined,
          default_visibility: visibility,
        }),
      });
      const json = await res.json();
      if (json.error) { setErr(json.error.message || 'Could not create the knowledge base'); return; }
      reset();
      onClose();
      onCreated(json.data);
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
          <label htmlFor="kb-new-name" className="block text-xs text-slate-400 mb-1.5">Name</label>
          <input
            id="kb-new-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Product Documentation"
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div>
          <label htmlFor="kb-new-description" className="block text-xs text-slate-400 mb-1.5">Description</label>
          <textarea
            id="kb-new-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What kind of documents will this contain?"
            rows={3}
            className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 resize-none focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label htmlFor="kb-new-project" className="block text-xs text-slate-400 mb-1.5">Project</label>
            <select
              id="kb-new-project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
            >
              <option value="">Default project</option>
              {(projects || []).filter((p) => p.name !== 'Default').map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="kb-new-visibility" className="block text-xs text-slate-400 mb-1.5">Who can read it</label>
            <select
              id="kb-new-visibility"
              value={visibility}
              onChange={(e) => setVisibility(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
            >
              <option value="project">Project members</option>
              <option value="tenant">Everyone in the organisation</option>
              <option value="private">Only me and people I share with</option>
            </select>
          </div>
        </div>
        <p className="text-[11px] text-slate-500 -mt-2">{VISIBILITY_HELP[visibility]}</p>
        {err && <p role="alert" className="text-xs text-red-400">{err}</p>}
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
  const [batchTotal, setBatchTotal] = useState(0);
  const [batchDone, setBatchDone] = useState(0);
  const [batchFailed, setBatchFailed] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // null when it worked, otherwise the reason
  const uploadOne = async (file: File): Promise<string | null> => {
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(`${API_URL}/api/knowledge-bases/${kbId}/upload`, {
        method: 'POST',
        headers: getAuthHeadersRaw(),
        body: form,
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json.error) {
        const m = typeof json.error === 'string' ? json.error : json.error?.message;
        return m || `upload failed (${res.status})`;
      }
      onUploaded(json.data);
      return null;
    } catch {
      return 'network error';
    }
  };

  const uploadBatch = async (files: File[]) => {
    if (!files.length) return;
    setUploading(true);
    setUploadError('');
    setBatchTotal(files.length);
    setBatchDone(0);
    setBatchFailed([]);
    const failed: string[] = [];
    for (const f of files) {
      const why = await uploadOne(f);
      if (why) failed.push(`${f.name} (${why})`);
      setBatchDone((n) => n + 1);
    }
    setBatchFailed(failed);
    if (failed.length > 0) {
      setUploadError(
        files.length === 1
          ? `Could not upload ${failed[0]}`
          : `${failed.length} of ${files.length} failed: ${failed.slice(0, 3).join(', ')}${failed.length > 3 ? '…' : ''}`,
      );
    }
    setUploading(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) uploadBatch(files);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length) uploadBatch(files);
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
        multiple
        onChange={handleFileChange}
        className="hidden"
        data-testid="kb-dropzone-input"
      />
      {uploading ? (
        <div className="flex flex-col items-center gap-2">
          <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
          <p className="text-xs text-slate-400">
            {batchTotal > 1
              ? `Uploading ${batchDone} of ${batchTotal}…`
              : 'Uploading...'}
          </p>
          {batchTotal > 1 && (
            <div className="w-48 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
              <div
                className="h-full bg-cyan-500 transition-all"
                style={{ width: `${(batchDone / batchTotal) * 100}%` }}
              />
            </div>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2">
          <Upload className={`w-6 h-6 ${dragging ? 'text-cyan-400' : 'text-slate-600'}`} />
          <p className="text-xs text-slate-400">
            Drop files (multiple OK) here or click to browse
          </p>
          <p className="text-[10px] text-slate-600">
            PDF, DOCX, TXT, CSV, MD, JSON (max 50 MB each)
          </p>
        </div>
      )}
      {uploadError && <p role="alert" data-testid="kb-upload-error" className="text-xs text-red-400 mt-2">{uploadError}</p>}
    </div>
  );
}

function KBDetailView({
  kb,
  onBack,
  onDeleted,
  justCreated,
  onDismissNext,
}: {
  kb: KBDetail;
  onBack: () => void;
  onDeleted: () => void;
  justCreated?: boolean;
  onDismissNext?: () => void;
}) {
  const [docs, setDocs] = useState<DocumentInfo[]>(kb.documents || []);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deletingKB, setDeletingKB] = useState(false);
  const [confirmDeleteKB, setConfirmDeleteKB] = useState(false);
  const [showShare, setShowShare] = useState(false);
  const [accessDoc, setAccessDoc] = useState<{ id: string; filename: string } | null>(null);
  const dropRef = useRef<HTMLDivElement>(null);

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
    const doc = docs.find((d) => d.id === docId);
    if (!window.confirm(`Delete ${doc?.filename || 'this document'}? Agents stop finding its content.`)) return;
    setDeleting(docId);
    try {
      const res = await fetch(`${API_URL}/api/knowledge-bases/${kb.id}/documents/${docId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error(String(res.status));
      setDocs((prev) => prev.filter((d) => d.id !== docId));
      toastSuccess('Document deleted');
    } catch {
      toastError('Failed to delete document');
    } finally {
      setDeleting(null);
    }
  };

  const deleteKB = async (force: boolean) => {
    setDeletingKB(true);
    try {
      await apiFetch(`/api/knowledge-bases/${kb.id}${force ? '?force=true' : ''}`, { method: 'DELETE' });
      onDeleted();
      toastSuccess('Knowledge base deleted');
    } catch (e: any) {
      toastError('Failed to delete knowledge base', e?.message);
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

      <PageHeader
        title={kb.name}
        purpose={kb.description || 'Upload documents here so agents can search them and answer from them.'}
        icon={Database}
        iconClassName="text-emerald-400"
        storageKey="knowledge-detail"
        docSlug="04-data-model/03-knowledge"
        meta={
          <span className={`text-xs px-2 py-0.5 rounded-full ${statusColor(kb.status)}`}>{kb.status}</span>
        }
        steps={[
          'Drop in PDFs, Word files, text, CSV, Markdown or JSON.',
          'Each file is split into small passages and indexed. That takes a few seconds per file.',
          'Once a file shows ready, add this knowledge base to an agent so it can search it.',
        ]}
        primaryAction={
          docs.some((d) => d.status === 'ready')
            ? { label: 'Use in an agent', icon: Bot, onClick: () => { window.location.href = `/builder?kb=${kb.id}`; }, testId: 'kb-use-in-agent' }
            : kb.can_edit !== false
              ? { label: 'Upload documents', icon: Upload, onClick: () => dropRef.current?.querySelector('input')?.click(), testId: 'kb-upload-primary' }
              : undefined
        }
        extraActions={
          <>
            {docs.some((d) => d.status === 'ready') && (
              <button
                onClick={() => { window.location.href = `/knowledge/${kb.id}/engine`; }}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-emerald-300 hover:text-white border border-emerald-500/30 hover:border-emerald-400 rounded-lg transition-colors"
                data-testid="kb-open-engine"
              >
                <Database className="w-3 h-3" /> Search this knowledge base
              </button>
            )}
            {kb.can_manage !== false && (
              <button
                onClick={() => setShowShare(true)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-slate-300 hover:text-white border border-slate-600/40 hover:border-slate-500 rounded-lg transition-colors"
                data-testid="kb-share"
              >
                <Share2 className="w-3 h-3" /> Share
              </button>
            )}
            {kb.can_edit !== false && (
              <button
                onClick={() => setConfirmDeleteKB(true)}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs text-red-400 hover:text-red-300 border border-red-500/20 hover:border-red-500/40 rounded-lg transition-colors"
              >
                <Trash2 className="w-3 h-3" />
                Delete KB
              </button>
            )}
          </>
        }
      >
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
          <span>{docs.length} document{docs.length === 1 ? '' : 's'}</span>
          <span>Chunk size: {kb.chunk_size}</span>
        </div>
      </PageHeader>

      {justCreated && (
        <NextSteps
          title="Knowledge base created. What next?"
          testId="kb-next-steps"
          onDismiss={onDismissNext}
          steps={[
            ...(kb.can_edit !== false
              ? [{ id: 'upload', label: 'Upload documents', hint: 'Add the files your agent should read.', icon: Upload, onClick: () => dropRef.current?.querySelector('input')?.click() }]
              : []),
            { id: 'agent', label: 'Use in an agent', hint: 'Open the builder with this knowledge base attached.', icon: Bot, href: `/builder?kb=${kb.id}` },
            { id: 'project', label: 'Group into a project', hint: 'Put related knowledge bases together.', icon: FolderOpen, href: '/knowledge/projects' },
          ]}
        />
      )}

      {kb.can_edit !== false ? (
        <div ref={dropRef}>
          <DropZone kbId={kb.id} onUploaded={handleUploaded} />
        </div>
      ) : (
        <p className="text-xs text-slate-400 border border-slate-700/50 rounded-lg px-3 py-2" data-testid="kb-read-only">
          You can search and use this knowledge base but not add documents to it. Ask {kb.owner_name || 'its owner'} for edit access.
        </p>
      )}

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
              data-testid="kb-doc-row" data-name={doc.filename} data-status={doc.status}
              className="flex items-center gap-3 p-3 bg-slate-800/30 border border-slate-700/50 rounded-lg group"
            >
              <div className="w-8 h-8 rounded-md bg-slate-700/50 flex items-center justify-center shrink-0">
                <FileText className="w-4 h-4 text-slate-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white truncate">{doc.filename}</p>
                {doc.status === 'failed' && doc.error_message && (
                  <p className="text-[11px] text-red-300 break-words" data-testid="kb-doc-error">{doc.error_message}</p>
                )}
                <div className="flex items-center gap-3 text-[10px] text-slate-500">
                  <span>{doc.file_type.toUpperCase()}</span>
                  <span>{formatSize(doc.file_size)}</span>
                  {doc.chunk_count > 0 && <span>{doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'}</span>}
                  {(doc.version_number || 1) > 1 && <span className="text-cyan-400" data-testid="kb-doc-version">v{doc.version_number}</span>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] px-2 py-0.5 rounded-full ${statusColor(doc.status)}`}>
                  {doc.status === 'processing' && (
                    <Loader2 className="w-2.5 h-2.5 animate-spin inline mr-1" />
                  )}
                  {doc.status}
                </span>
                {kb.can_edit !== false && (
                  <button
                    onClick={() => setAccessDoc({ id: doc.id, filename: doc.filename })}
                    aria-label={`Who can read ${doc.filename}`}
                    title="Who can read it, and its versions"
                    data-testid="kb-doc-access"
                    className="text-slate-500 hover:text-emerald-400 transition-colors"
                  >
                    <Lock className="w-3.5 h-3.5" />
                  </button>
                )}
                <button
                  onClick={() => deleteDoc(doc.id)}
                  disabled={deleting === doc.id}
                  aria-label={`Delete ${doc.filename}`}
                  className="text-slate-500 hover:text-red-400 transition-colors md:opacity-0 md:group-hover:opacity-100 focus:opacity-100 disabled:opacity-50"
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
      <DeleteWithDependents
        open={confirmDeleteKB}
        onClose={() => setConfirmDeleteKB(false)}
        resource={`/api/knowledge-bases/${kb.id}`}
        name={kb.name}
        what="knowledge base"
        note="Its documents and embeddings are removed permanently."
        onConfirm={deleteKB}
      />
      <DocumentAccessModal kbId={kb.id} doc={accessDoc} onClose={() => setAccessDoc(null)} />
      <ResourceShareDialog
        open={showShare}
        onClose={() => setShowShare(false)}
        resourceType="knowledge_base"
        resourceId={kb.id}
        resourceName={kb.name}
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
  const [createdId, setCreatedId] = useState<string | null>(null);
  const LIMIT = 20;

  const apiUrl = `/api/knowledge-bases?search=${encodeURIComponent(search)}&status=${encodeURIComponent(statusFilter)}&sort=${sortBy}&limit=${LIMIT}&offset=${page * LIMIT}`;
  const [deletingCard, setDeletingCard] = useState<{ id: string; name: string } | null>(null);
  const { data: kbs, isLoading: loading, meta, mutate: mutateKBs } =
    useApi<KnowledgeBase[]>(apiUrl, { keepPreviousData: true });

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

  const searchParams = useSearchParams();
  const router = useRouter();
  const queryId = searchParams?.get('id') || null;
  const queryProject = searchParams?.get('project') || '';
  const queryNew = searchParams?.get('new') === '1';

  useEffect(() => {
    if (queryNew) setModalOpen(true);
  }, [queryNew]);

  // the sidebar link to /knowledge drops the id, go back to the list
  useEffect(() => {
    if (!queryId) setSelectedKB(null);
  }, [queryId]);

  useEffect(() => {
    if (!queryId || selectedKB?.id === queryId) return;
    void openDetail(queryId);
  // openDetail closes over apiFetch and setState only; queryId is the trigger
  }, [queryId, selectedKB?.id]);

  const closeDetail = () => {
    setSelectedKB(null);
    if (queryId) router.replace('/knowledge');
  };

  // straight into the new KB so the upload box is right there
  const handleCreated = (kb: KnowledgeBase) => {
    mutateKBs();
    if (kb?.id) {
      setCreatedId(kb.id);
      router.replace(`/knowledge?id=${kb.id}`);
    }
  };

  const handleKBDeleted = () => {
    setSelectedKB(null);
    if (queryId) router.replace('/knowledge');
    mutateKBs();
  };

  if (loading && !kbs) {
    return <KnowledgeSkeleton />;
  }

  if (selectedKB) {
    return (
      <div className="max-w-[900px]">
        <KBDetailView
          kb={selectedKB}
          onBack={closeDetail}
          onDeleted={handleKBDeleted}
          justCreated={createdId === selectedKB.id}
          onDismissNext={() => setCreatedId(null)}
        />
      </div>
    );
  }

  if (queryId && loadingDetail) {
    return <KnowledgeSkeleton />;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-[1400px]"
    >
      <PageHeader
        title="Knowledge Bases"
        purpose="Upload documents your agents can search and quote from. For anyone building agents."
        icon={Database}
        iconClassName="text-emerald-400"
        storageKey="knowledge"
        docSlug="04-data-model/03-knowledge"
        steps={[
          'Create a knowledge base and give it a clear name.',
          'Upload PDFs, Word files, text or spreadsheets. Each file is split into passages and indexed.',
          'Attach it to an agent in the builder so the agent can search it while it answers.',
          'Group related knowledge bases into projects when you have many.',
        ]}
        primaryAction={{ label: 'New Knowledge Base', icon: Plus, onClick: () => setModalOpen(true) }}
        secondaryAction={{ label: 'Projects', icon: FolderOpen, href: '/knowledge/projects' }}
      />

      {/* Search & Filters */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search knowledge bases..."
            aria-label="Search knowledge bases"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }}
            className="w-full pl-10 pr-4 py-2 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
          />
        </div>
        <select
          aria-label="Filter by status"
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

      {(kbs ?? []).length === 0 && !loading && (search || statusFilter ? (
        <EmptyState
          icon={Database}
          title="No knowledge bases match"
          description="Try another name or clear the status filter."
        />
      ) : (
        <EmptyState
          icon={Database}
          title="No knowledge bases yet"
          description="Upload documents to get started with RAG-powered agents."
          actionLabel="New Knowledge Base"
          onAction={() => setModalOpen(true)}
        />
      ))}

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <AnimatePresence>
          {(kbs ?? []).map((kb) => (
            <motion.div
              key={kb.id}
              layout
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              onClick={() => router.push(`/knowledge?id=${kb.id}`)}
              data-testid="kb-card" data-name={kb.name} data-status={kb.status}
              className="relative bg-slate-800/30 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-colors cursor-pointer group"
            >
              {kb.can_edit !== false && <button
                onClick={(e) => {
                  e.stopPropagation();
                  setDeletingCard({ id: kb.id, name: kb.name });
                }}
                data-testid={`kb-delete-${kb.id}`}
                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 p-1.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-all"
                aria-label="Delete knowledge base"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>}
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
              <h3 className="text-sm font-semibold text-white mb-1">{kb.name}</h3>
              <OwnerBadge ownership={kb.ownership} ownerName={kb.owner_name} className="mb-2" />
              <div className="space-y-1.5 text-xs text-slate-500">
                <div className="flex items-center gap-2">
                  <FileText className="w-3 h-3" /> {kb.doc_count} document{kb.doc_count === 1 ? '' : 's'}
                </div>
                <div className="flex items-center gap-2">
                  <Database className="w-3 h-3" /> {(kb.chunk_count || 0).toLocaleString()} chunk{kb.chunk_count === 1 ? '' : 's'}
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
                  data-testid="kb-card-engine"
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

      <CreateModal
        open={modalOpen}
        onClose={() => { setModalOpen(false); if (queryNew) router.replace('/knowledge'); }}
        onCreated={handleCreated}
        initialProject={queryProject}
      />
      <DeleteWithDependents
        open={!!deletingCard}
        onClose={() => setDeletingCard(null)}
        resource={`/api/knowledge-bases/${deletingCard?.id}`}
        name={deletingCard?.name || ''}
        what="knowledge base"
        note="Its documents and embeddings are removed permanently."
        onConfirm={async (force) => {
          if (!deletingCard) return;
          try {
            await apiFetch(`/api/knowledge-bases/${deletingCard.id}${force ? '?force=true' : ''}`, { method: 'DELETE' });
            toastSuccess('Knowledge base deleted');
            mutateKBs();
          } catch (e: any) {
            toastError('Failed to delete knowledge base', e?.message);
          }
        }}
      />
    </motion.div>
  );
}
