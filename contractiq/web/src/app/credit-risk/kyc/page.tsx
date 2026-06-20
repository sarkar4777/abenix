'use client';

import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { PageExplainer } from '@/components/PageExplainer';
import {
  ShieldCheck, ShieldAlert, Plus, Loader2, ChevronRight,
  CheckCircle2, XCircle, AlertTriangle, FileCheck2, Building2,
  Flag, Upload, FileText, Download, Play, Printer, DollarSign,
} from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '';
function getToken() { if (typeof window === 'undefined') return null; return localStorage.getItem('contractiq_token'); }

interface KycCheck {
  id: string;
  status: string;
  counterparty: { name: string; country_name?: string; country_iso2?: string; primary_business?: string };
  activity_trigger?: string;
  type_of_business_relationship?: string;
  aggregated_score?: number;
  type_of_check?: string;
  outcome_of_check?: string;
  local_kyc_expert_name?: string;
  signed_at?: string;
  local_kyc_signed_at?: string;
  compliance_mgr_signed_at?: string;
  group_compliance_signed_at?: string;
  next_review_due?: string;
  end_date_of_check?: string;
  notional_currency?: string;
  created_at?: string;
  tool_warnings?: string[];
  raw_agent_response?: any;
  indicator_i?: { score?: number; rationale?: string };
  indicator_ii?: { score?: number; rationale?: string };
  indicator_iii?: { score?: number; rationale?: string };
  intermediate_checks?: Array<{ item?: string; name?: string; label?: string; outcome?: string; status?: string; risk?: string; risk_grade?: string; comment?: string }>;
  sanctions_applicable?: boolean;
}

interface Validation {
  field: string;
  status: 'ok' | 'inconsistent' | 'missing' | string;
  note?: string;
}

interface ReconciliationReport {
  extracted?: any;
  validations?: Validation[];
  reconciled_record?: any;
  confidence?: number;
  requires_human_review?: boolean;
  tool_warnings?: string[];
}

const CHECK_COLORS: Record<string, string> = {
  Simplified: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  Standard: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  Enhanced: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  Special: 'text-red-400 bg-red-500/10 border-red-500/30',
};

const OUTCOME_COLORS: Record<string, string> = {
  positive: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  positive_with_conditions: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
  negative: 'text-red-400 bg-red-500/10 border-red-500/30',
  pending: 'text-slate-400 bg-slate-500/10 border-slate-500/30',
  needs_review: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
};

const OUTCOME_LABEL: Record<string, string> = {
  positive: 'POSITIVE',
  positive_with_conditions: 'POSITIVE WITH CONDITIONS',
  negative: 'NEGATIVE',
  pending: 'PENDING',
  needs_review: 'NEEDS REVIEW',
};

const OUTCOME_ACTION: Record<string, string> = {
  positive: 'ENTER',
  positive_with_conditions: 'CONDITIONAL — REQUIRES COMPLIANCE SIGN-OFF',
  negative: 'DO NOT ENTER',
  pending: 'AWAITING REVIEW',
  needs_review: 'PENDING REVIEW',
};

const VALIDATION_BADGE: Record<string, string> = {
  ok: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
  inconsistent: 'text-red-400 bg-red-500/10 border-red-500/30',
  missing: 'text-amber-400 bg-amber-500/10 border-amber-500/30',
};

const RISK_BG: Record<string, string> = {
  L: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  M: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  H: 'bg-red-500/15 text-red-300 border-red-500/40',
};

const STATUS_COLOR: Record<string, string> = {
  OK: 'text-emerald-400',
  PASS: 'text-emerald-400',
  FAIL: 'text-red-400',
  'N-A': 'text-slate-400',
  NA: 'text-slate-400',
  PENDING: 'text-slate-400',
};

const CURRENCIES = ['EUR', 'GBP', 'USD', 'CHF', 'PLN'];

const COUNTRIES: { code: string; name: string }[] = [
  { code: 'US', name: 'United States' }, { code: 'GB', name: 'United Kingdom' },
  { code: 'DE', name: 'Germany' }, { code: 'FR', name: 'France' }, { code: 'IT', name: 'Italy' },
  { code: 'ES', name: 'Spain' }, { code: 'NL', name: 'Netherlands' }, { code: 'BE', name: 'Belgium' },
  { code: 'PL', name: 'Poland' }, { code: 'CZ', name: 'Czechia' }, { code: 'AT', name: 'Austria' },
  { code: 'CH', name: 'Switzerland' }, { code: 'SE', name: 'Sweden' }, { code: 'NO', name: 'Norway' },
  { code: 'DK', name: 'Denmark' }, { code: 'FI', name: 'Finland' }, { code: 'IE', name: 'Ireland' },
  { code: 'PT', name: 'Portugal' }, { code: 'GR', name: 'Greece' }, { code: 'HU', name: 'Hungary' },
  { code: 'TR', name: 'Turkey' }, { code: 'RU', name: 'Russia' }, { code: 'UA', name: 'Ukraine' },
  { code: 'CN', name: 'China' }, { code: 'HK', name: 'Hong Kong' }, { code: 'JP', name: 'Japan' },
  { code: 'KR', name: 'South Korea' }, { code: 'SG', name: 'Singapore' }, { code: 'IN', name: 'India' },
  { code: 'AE', name: 'United Arab Emirates' }, { code: 'SA', name: 'Saudi Arabia' }, { code: 'IL', name: 'Israel' },
  { code: 'ZA', name: 'South Africa' }, { code: 'BR', name: 'Brazil' }, { code: 'MX', name: 'Mexico' },
  { code: 'CA', name: 'Canada' }, { code: 'AU', name: 'Australia' }, { code: 'NZ', name: 'New Zealand' },
  { code: 'MT', name: 'Malta' },
];

interface IndustryOpt { key: string; label: string }

export default function KycListPage() {
  const router = useRouter();
  const [checks, setChecks] = useState<KycCheck[]>([]);
  const [loading, setLoading] = useState(true);
  const [industries, setIndustries] = useState<IndustryOpt[]>([]);

  // ── New-KYC form (MET-template aligned) ──
  const [form, setForm] = useState({
    activity_trigger: 'Pre-Check',
    business_relationship: 'Noncore',
    counterparty_name: '',
    address: '',
    country_iso2: '',
    industry_segment: '',
    annual_notional_usd: '' as string | number,
    currency: 'EUR',
    primary_business: '',
    description: '',
  });
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [latest, setLatest] = useState<KycCheck | null>(null);
  const [refreshOfId, setRefreshOfId] = useState<string | null>(null);

  // Server-driven pre-screen result
  const [prescreen, setPrescreen] = useState<null | { flagged: boolean; fatf_status?: string; ofac_programs?: string[]; jurisdiction_risk_grade?: string }>(null);

  // Server-driven dedup banner
  const [dedupHit, setDedupHit] = useState<null | { kyc_id: string; signed_at?: string; next_review_due?: string }>(null);

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }));

  // ── PDF import workflow ──
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [report, setReport] = useState<ReconciliationReport | null>(null);
  const [importedKycId, setImportedKycId] = useState<string | null>(null);
  const [originalPdfUrl, setOriginalPdfUrl] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Multi-file bulk import queue.
  type QueueRow = {
    name: string;
    status: 'queued' | 'processing' | 'done' | 'failed' | 'duplicate';
    row_id?: string;
    error?: string;
    steps?: { step: string; at?: string; error?: string }[];
  };
  const [importQueue, setImportQueue] = useState<QueueRow[]>([]);
  const [duplicateBanners, setDuplicateBanners] = useState<Array<{
    filename: string; existing_kyc_id: string; imported_at?: string; counterparty_name?: string;
  }>>([]);

  // Inline-edit state — dirty flag forces a save before sign-off.
  const [edits, setEdits] = useState<Record<string, any>>({});
  const [savingEdit, setSavingEdit] = useState(false);
  const [showHumanReviewReason, setShowHumanReviewReason] = useState(false);
  const [humanReviewReason, setHumanReviewReason] = useState('');
  const [filterImported, setFilterImported] = useState(false);

  const fetchData = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const j = await r.json();
      if (j.data) setChecks(j.data);
    } catch { /* silent */ }
    setLoading(false);
  }, []);

  // Load industry options from the agent-backed endpoint
  useEffect(() => {
    const t = getToken();
    if (!t) return;
    (async () => {
      try {
        const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/industry-options`, {
          headers: { Authorization: `Bearer ${t}` },
        });
        const j = await r.json();
        if (j.data?.industries) {
          setIndustries(j.data.industries.map((it: any) => ({ key: it.key, label: it.label })));
        }
      } catch { /* silent */ }
    })();
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Pre-screen + dedup lookups when country / name change
  useEffect(() => {
    const iso = form.country_iso2.trim().toUpperCase();
    if (!/^[A-Z]{2}$/.test(iso)) { setPrescreen(null); return; }
    const t = getToken();
    if (!t) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/prescreen?country=${iso}`, {
          headers: { Authorization: `Bearer ${t}` },
        });
        const j = await r.json();
        if (!cancelled && j.data) setPrescreen(j.data);
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [form.country_iso2]);

  const lookupDedup = async () => {
    const name = form.counterparty_name.trim();
    const iso = form.country_iso2.trim().toUpperCase();
    if (!name || !/^[A-Z]{2}$/.test(iso)) return;
    const t = getToken();
    if (!t) return;
    try {
      const r = await fetch(
        `${API_URL}/api/contractiq/insights/kyc/lookup?name=${encodeURIComponent(name)}&country=${iso}`,
        { headers: { Authorization: `Bearer ${t}` } },
      );
      const j = await r.json();
      if (j.data?.hit) {
        setDedupHit({
          kyc_id: j.data.kyc_id,
          signed_at: j.data.local_kyc_signed_at || j.data.signed_at,
          next_review_due: j.data.next_review_due,
        });
      } else {
        setDedupHit(null);
      }
    } catch { /* silent */ }
  };

  const canSubmit = useMemo(() => (
    form.counterparty_name.trim().length > 1
    && /^[A-Z]{2}$/.test(form.country_iso2.trim().toUpperCase())
    && !!form.industry_segment
    && Number(form.annual_notional_usd) > 0
  ), [form]);

  const runKyc = async () => {
    if (!canSubmit) {
      setRunError('Fill counterparty name, ISO-2 country, industry, and notional.');
      return;
    }
    setRunError(null);
    setRunning(true);
    setLatest(null);

    try {
      const triggerMap: Record<string, string> = {
        'Pre-Check': 'pre',
        'Periodic Check': 'periodic',
        'Ad-hoc Check': 'ad_hoc',
      };
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/run`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          counterparty_name: form.counterparty_name.trim(),
          address: form.address.trim(),
          country_iso2: form.country_iso2.trim().toUpperCase(),
          country_iso: form.country_iso2.trim().toUpperCase(),
          industry_segment: form.industry_segment,
          annual_notional_usd: Number(form.annual_notional_usd),
          currency: form.currency,
          activity_trigger: triggerMap[form.activity_trigger] || 'pre',
          business_relationship: form.business_relationship.toLowerCase(),
          primary_business: form.primary_business || undefined,
          description: form.description || undefined,
          refresh_of_kyc_id: refreshOfId || undefined,
        }),
      });
      const j = await r.json();
      if (j.error) {
        setRunError(j.error.message || j.error);
        setRunning(false);
        return;
      }
      if (j.data) {
        setLatest(j.data);
        await fetchData();
      }
    } catch (e: any) {
      setRunError(e.message || 'Request failed');
    }
    setRunning(false);
  };

  const exportPdf = async (id: string, name: string) => {
    setRunError(null);
    try {
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/${id}/pdf/render`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!r.ok) { setRunError('PDF export failed (server returned ' + r.status + ').'); return; }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `kyc_${name.replace(/\s+/g, '_').slice(0, 40)}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setRunError('PDF export failed: ' + (e?.message || e));
    }
  };

  // ── PDF import handlers (bulk-aware) ──
  // Single coalesced poller. Given a map of kyc_id → queue-index, hit the
  // batch endpoint every 2s and update every row in one round-trip. Beats
  // firing N parallel pollers (each its own fetch loop).
  const pollJobStatusBatch = async (idToQIdx: Record<string, number>) => {
    const token = getToken();
    if (!token) return;
    const stop = Date.now() + 480000;
    const ids = Object.keys(idToQIdx);
    if (!ids.length) return;
    const pending = new Set(ids);
    while (Date.now() < stop && pending.size) {
      try {
        const qs = Array.from(pending).join(',');
        const r = await fetch(
          `${API_URL}/api/contractiq/insights/kyc-batch/status?ids=${encodeURIComponent(qs)}`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        const j = await r.json();
        const jobs: Array<{ kyc_id: string; status: string; status_steps?: any[] }> =
          (j.data || j)?.jobs || [];
        setImportQueue(q => {
          const next = [...q];
          for (const d of jobs) {
            const qIdx = idToQIdx[d.kyc_id];
            if (typeof qIdx === 'number' && next[qIdx]) {
              next[qIdx] = {
                ...next[qIdx],
                steps: d.status_steps || next[qIdx].steps,
                status: d.status === 'completed' ? 'done'
                  : d.status === 'failed' ? 'failed'
                  : 'processing',
              };
            }
            if (d.status === 'completed' || d.status === 'failed') pending.delete(d.kyc_id);
          }
          return next;
        });
      } catch { /* silent */ }
      if (!pending.size) return;
      await new Promise(r => setTimeout(r, 2000));
    }
  };

  const handleFiles = async (fileList: FileList | File[]) => {
    const arr = Array.from(fileList);
    if (!arr.length) return;
    setImporting(true);
    setImportError(null);
    setReport(null);
    setImportedKycId(null);
    setOriginalPdfUrl(null);
    setDuplicateBanners([]);

    const startIndex = importQueue.length;
    setImportQueue(q => [
      ...q,
      ...arr.map(f => ({ name: f.name, status: 'queued' as const })),
    ]);

    const token = getToken();
    if (!token) { setImportError('Not authenticated'); setImporting(false); return; }
    try {
      const fd = new FormData();
      arr.forEach(f => fd.append('files', f));
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/import`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const j = await r.json();
      if (!r.ok) {
        const dupes = j.error?.duplicates;
        if (r.status === 409 && Array.isArray(dupes)) {
          setDuplicateBanners(dupes);
          setImportQueue(q => {
            const next = [...q];
            for (let i = 0; i < arr.length; i++) {
              if (next[startIndex + i]) {
                next[startIndex + i] = {
                  ...next[startIndex + i],
                  status: 'duplicate',
                };
              }
            }
            return next;
          });
          return;
        }
        setImportError(j.detail || j.error?.message || j.message || `HTTP ${r.status}`);
        setImportQueue(q => {
          const next = [...q];
          for (let i = 0; i < arr.length; i++) {
            if (next[startIndex + i]) {
              next[startIndex + i] = {
                ...next[startIndex + i],
                status: 'failed',
                error: j.error?.message || `HTTP ${r.status}`,
              };
            }
          }
          return next;
        });
        return;
      }
      const payload = j.data || j;
      const jobs: Array<{ kyc_id: string; filename: string; status: string }> = payload.jobs || [];
      if (Array.isArray(payload.duplicates) && payload.duplicates.length) {
        setDuplicateBanners(payload.duplicates);
      }
      setImportQueue(q => {
        const next = [...q];
        jobs.forEach((j, idx) => {
          const target = next[startIndex + idx];
          if (target) {
            next[startIndex + idx] = {
              ...target,
              row_id: j.kyc_id,
              status: j.status === 'completed' ? 'done' : j.status === 'failed' ? 'failed' : 'processing',
            };
          }
        });
        return next;
      });
      // Single-file legacy path still surfaces the report inline.
      if (jobs.length === 1) {
        setImportedKycId(payload.kyc_id || jobs[0].kyc_id || null);
        setOriginalPdfUrl(payload.original_pdf_url || null);
        setReport(payload.reconciliation_report || null);
        setEdits({});
      }
      // Coalesce every still-processing job into a single batch poller.
      const idToQIdx: Record<string, number> = {};
      jobs.forEach((j, idx) => {
        if (j.kyc_id && (j.status === 'running' || j.status === 'processing')) {
          idToQIdx[j.kyc_id] = startIndex + idx;
        }
      });
      if (Object.keys(idToQIdx).length) pollJobStatusBatch(idToQIdx);
      fetchData();
    } catch (e: any) {
      setImportError(String(e?.message || e));
    } finally {
      setImporting(false);
    }
  };

  const handleFile = (file: File) => handleFiles([file]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDragActive(false);
    const fs = e.dataTransfer.files; if (fs?.length) handleFiles(fs);
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const fs = e.target.files; if (fs?.length) handleFiles(fs);
  };

  const inconsistencies = (report?.validations || []).filter(v => v.status === 'inconsistent');
  const intermediateForSignOff: any[] = Array.isArray(report?.reconciled_record?.intermediate_checks)
    ? report?.reconciled_record?.intermediate_checks
    : [];
  const intermediateUnwrap = (val: any) => (val && typeof val === 'object' && 'value' in val) ? val.value : val;
  const hasHGrade = intermediateForSignOff.some((c: any) => {
    const r = intermediateUnwrap(c.risk_grade) || intermediateUnwrap(c.risk);
    return typeof r === 'string' && r.toUpperCase() === 'H';
  });
  const dirty = Object.keys(edits).length > 0;
  const canAutoSignOff =
    !!report &&
    inconsistencies.length === 0 &&
    !report.requires_human_review &&
    !hasHGrade &&
    !dirty;

  const savePendingEdits = async () => {
    if (!importedKycId || !dirty) return;
    setSavingEdit(true);
    try {
      const token = getToken();
      const r = await fetch(`${API_URL}/api/contractiq/insights/kyc/${importedKycId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(edits),
      });
      if (r.ok) {
        setEdits({});
        // Refetch the authoritative row from the server so requires_human_review
        // and intermediate_checks reflect the server-side recompute, not the
        // stale in-memory `report` snapshot we used during editing.
        try {
          const fresh = await fetch(
            `${API_URL}/api/contractiq/insights/kyc/${importedKycId}`,
            { headers: { Authorization: `Bearer ${token}` } },
          );
          if (fresh.ok) {
            const fj = await fresh.json();
            const serv = fj.data || fj;
            setReport(prev => prev ? ({
              ...prev,
              requires_human_review: serv.requires_human_review,
              reconciled_record: {
                ...(prev.reconciled_record || {}),
                intermediate_checks: serv.intermediate_checks,
                outcome_of_check: serv.outcome_of_check,
                type_of_check: serv.type_of_check,
                counterparty: { ...(prev.reconciled_record?.counterparty || {}), ...(serv.counterparty || {}) },
              },
            }) : prev);
          }
        } catch { /* silent — keep current state if refetch fails */ }
      }
    } catch { /* silent */ } finally {
      setSavingEdit(false);
    }
  };

  const discardImport = async () => {
    if (!importedKycId) return;
    if (!confirm('Discard this import? The PDF and partial KYC row will be deleted.')) return;
    const token = getToken();
    try {
      await fetch(`${API_URL}/api/contractiq/insights/kyc/${importedKycId}/discard`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch { /* silent */ }
    setReport(null);
    setImportedKycId(null);
    setOriginalPdfUrl(null);
    setEdits({});
    fetchData();
  };

  const signOffImported = async (humanReview: boolean) => {
    if (!importedKycId) return;
    const token = getToken();
    if (!token) return;
    if (humanReview && !humanReviewReason.trim()) {
      setShowHumanReviewReason(true);
      return;
    }
    // needs_review outcome doesn't lock the row as DO-NOT-ENTER — it parks
    // it for a senior reviewer, with the officer's reason captured.
    const outcome = humanReview
      ? 'needs_review'
      : (report?.reconciled_record?.outcome_of_check || 'positive');
    await fetch(`${API_URL}/api/contractiq/insights/kyc/${importedKycId}/sign-off`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        role: 'local_kyc',
        outcome_of_check: outcome,
        general_comments: humanReview
          ? `Needs senior review: ${humanReviewReason.trim()}`
          : 'Auto-approved on import',
      }),
    });
    setReport(null);
    setImportedKycId(null);
    setOriginalPdfUrl(null);
    setEdits({});
    setHumanReviewReason('');
    setShowHumanReviewReason(false);
    fetchData();
  };

  const counts = {
    total: checks.length,
    running: checks.filter(c => c.status === 'running').length,
    completed: checks.filter(c => c.status === 'completed').length,
    signed: checks.filter(c => c.signed_at || c.local_kyc_signed_at).length,
    enhanced: checks.filter(c => c.type_of_check === 'Enhanced' || c.type_of_check === 'Special').length,
  };

  if (loading) return (
    <div className="min-h-screen bg-[#0B0F19] flex items-center justify-center">
      <Loader2 className="w-8 h-8 text-emerald-400 animate-spin" />
    </div>
  );

  // ── Tri-indicator panel data ──
  const triI = latest?.indicator_i?.score;
  const triII = latest?.indicator_ii?.score;
  const triIII = latest?.indicator_iii?.score;
  const aggregated = latest?.aggregated_score;
  // Tier comes from the agent — never recomputed client-side
  const tier = latest?.type_of_check;

  const matrixItems = latest?.intermediate_checks || [];
  const outcome = (latest?.outcome_of_check || '').toLowerCase();
  const outcomeKey = (['positive', 'positive_with_conditions', 'negative', 'pending'].includes(outcome) ? outcome : 'pending');

  const today = new Date();
  const ninetyDays = new Date(); ninetyDays.setDate(today.getDate() + 90);

  return (
    <div className="min-h-screen bg-[#0B0F19] p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <a href="/credit-risk" className="hover:text-slate-300">Counterparty Risk</a>
              <ChevronRight className="w-3 h-3" />
              <span>KYC Standard Checks</span>
            </div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3 mt-1">
              <FileCheck2 className="w-7 h-7 text-cyan-400" />
              KYC Standard Check
              <span
                title="MET-style template: tri-indicator scoring (Country CPI + Notional + Industry) + an intermediate compliance checklist + a documented outcome."
                className="text-[10px] font-medium px-2 py-0.5 rounded-full border border-cyan-500/40 bg-cyan-500/10 text-cyan-300 cursor-help"
              >
                MET template
              </span>
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              MET-style template — tri-indicator scoring + intermediate compliance checklist + outcome. Tier = Standard / Enhanced / Special.
            </p>
          </div>
          <div className="flex gap-2">
            <a
              href="/credit-risk/kyc/new"
              className="px-4 py-2 rounded-lg bg-slate-800/60 border border-slate-700 text-slate-200 text-sm font-medium flex items-center gap-2 hover:bg-slate-700"
            >
              <Plus className="w-4 h-4" /> Advanced (from contracts)
            </a>
          </div>
        </div>
        <PageExplainer routeKey="credit-risk-kyc" />

        {/* ── MET form ── */}
        <section
          data-testid="kyc-met-form"
          className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-5 space-y-4"
        >
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <Building2 className="w-4 h-4 text-cyan-400" /> New KYC Check — MET Template
          </h2>

          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-xs text-slate-400">Activity Trigger:</span>
            <div className="flex gap-2" data-testid="kyc-trigger-pills">
              {['Pre-Check', 'Periodic Check', 'Ad-hoc Check'].map(t => {
                const active = form.activity_trigger === t;
                return (
                  <button
                    key={t}
                    onClick={() => set('activity_trigger', t)}
                    data-testid={`kyc-trigger-${t.replace(/\s+/g, '-')}`}
                    className={`px-3 py-1 rounded-full border text-xs transition ${active ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-300' : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'}`}
                  >
                    {t}
                  </button>
                );
              })}
            </div>
            <span className="text-xs text-slate-400 ml-4">Business Relationship:</span>
            <div className="flex gap-2" data-testid="kyc-relationship-toggle">
              {['Core', 'Noncore'].map(r => {
                const active = form.business_relationship === r;
                return (
                  <button
                    key={r}
                    onClick={() => set('business_relationship', r)}
                    data-testid={`kyc-relationship-${r}`}
                    className={`px-3 py-1 rounded-full border text-xs transition ${active ? 'bg-cyan-500/15 border-cyan-500/40 text-cyan-300' : 'bg-slate-900 border-slate-700 text-slate-400 hover:text-slate-200'}`}
                  >
                    {r}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* Card 1 — Counterparty Identity */}
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-xl p-4 space-y-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Counterparty Identity</p>
              <label className="block text-xs text-slate-400">
                Counterparty Name <span className="text-red-400">*</span>
                <input
                  value={form.counterparty_name}
                  onChange={e => set('counterparty_name', e.target.value)}
                  onBlur={lookupDedup}
                  placeholder="Full legal name"
                  data-testid="kyc-name"
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                />
              </label>
              <label className="block text-xs text-slate-400">
                Address
                <input
                  value={form.address}
                  onChange={e => set('address', e.target.value)}
                  placeholder="Full registered address"
                  data-testid="kyc-address"
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                />
              </label>
              <label className="block text-xs text-slate-400">
                Country (ISO-2) <span className="text-red-400">*</span>
                <select
                  value={form.country_iso2}
                  onChange={e => set('country_iso2', e.target.value)}
                  onBlur={lookupDedup}
                  data-testid="kyc-country"
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                >
                  <option value="">— Select —</option>
                  {COUNTRIES.map(c => (
                    <option key={c.code} value={c.code}>{c.code} — {c.name}</option>
                  ))}
                </select>
              </label>
            </div>

            {/* Card 2 — Commercial Context */}
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-xl p-4 space-y-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Commercial Context</p>
              <label className="block text-xs text-slate-400">
                Industry Segment <span className="text-red-400">*</span>
                <select
                  value={form.industry_segment}
                  onChange={e => set('industry_segment', e.target.value)}
                  data-testid="kyc-industry"
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                >
                  <option value="">{industries.length ? '— Select —' : 'Loading…'}</option>
                  {industries.map(i => (
                    <option key={i.key} value={i.key}>{i.label}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-slate-400">
                Annual Contracted Volume / Notional <span className="text-red-400">*</span>
                <div className="mt-1 flex gap-2">
                  <input
                    type="number"
                    min={1}
                    value={form.annual_notional_usd}
                    onChange={e => set('annual_notional_usd', e.target.value)}
                    placeholder="e.g. 20000000"
                    data-testid="kyc-notional"
                    className="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  />
                  <select
                    value={form.currency}
                    onChange={e => set('currency', e.target.value)}
                    data-testid="kyc-currency"
                    className="w-24 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white focus:border-emerald-500/60 focus:outline-none"
                  >
                    {CURRENCIES.map(c => (<option key={c} value={c}>{c}</option>))}
                  </select>
                </div>
              </label>
              <label className="block text-xs text-slate-400">
                Primary Business <span className="text-slate-600">(optional)</span>
                <input
                  value={form.primary_business}
                  onChange={e => set('primary_business', e.target.value)}
                  placeholder="e.g. Wood, Furniture & Paper Manufacturing"
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-white placeholder-slate-600 focus:border-emerald-500/60 focus:outline-none"
                />
              </label>
            </div>

            {/* Card 3 — Compliance Posture */}
            <div className="bg-slate-900/40 border border-slate-700/40 rounded-xl p-4 space-y-3">
              <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Compliance Posture</p>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                Pre-screen and dedup hits surface here once Country and Counterparty Name are filled. Live screening still runs against OFAC/EU/UN/UK at submission time.
              </p>
              {!prescreen && !dedupHit && (
                <p className="text-[11px] text-slate-600 italic">Fill identity to populate.</p>
              )}
            </div>
          </div>

          {/* Dedup banner (server-driven) */}
          {dedupHit && (
            <div data-testid="kyc-dedup-banner" className="flex items-start gap-2 text-xs text-cyan-200 bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-3">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-cyan-300" />
              <div className="flex-1">
                We already have a KYC on this name
                {dedupHit.signed_at ? ` signed ${new Date(dedupHit.signed_at).toISOString().slice(0,10)}` : ''}
                {dedupHit.next_review_due ? `, next review ${new Date(dedupHit.next_review_due).toISOString().slice(0,10)}` : ''}.
                <button
                  onClick={() => setRefreshOfId(dedupHit.kyc_id)}
                  className="ml-2 underline hover:text-white"
                  data-testid="kyc-dedup-refresh"
                >
                  Refresh existing?
                </button>
                {refreshOfId === dedupHit.kyc_id && (
                  <span className="ml-2 text-emerald-300">(linked as refresh)</span>
                )}
              </div>
            </div>
          )}

          {/* Server-driven sanctions / jurisdiction pre-screen banner */}
          {prescreen?.flagged && (
            <div
              data-testid="kyc-sanctions-prescreen-banner"
              className="flex items-start gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-3"
            >
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-red-400" />
              <span>
                Pre-screen: <b>{form.country_iso2.toUpperCase()}</b> flagged
                {prescreen.fatf_status && prescreen.fatf_status !== 'clear' ? ` — FATF ${prescreen.fatf_status}` : ''}
                {prescreen.ofac_programs?.length ? ` — OFAC: ${prescreen.ofac_programs.join(', ')}` : ''}
                . This may force tier = <b>Special</b>.
              </span>
            </div>
          )}
          {prescreen && !prescreen.flagged && (
            <div
              data-testid="kyc-sanctions-prescreen-banner"
              className="flex items-start gap-2 text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-3"
            >
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400" />
              <span>Pre-screen clear for <b>{form.country_iso2.toUpperCase()}</b>. Live screening still runs against OFAC/EU/UN/UK.</span>
            </div>
          )}

          {runError && (
            <div data-testid="kyc-run-error" className="flex items-start gap-2 text-xs text-rose-400 bg-rose-500/5 border border-rose-500/20 rounded-lg p-3">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" /> {runError}
            </div>
          )}

          <div className="flex justify-end">
            <button
              onClick={runKyc}
              disabled={running || !canSubmit}
              data-testid="kyc-run"
              className="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-500 to-cyan-600 text-white font-semibold text-sm flex items-center gap-2 hover:shadow-lg hover:shadow-emerald-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {running
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Running checks (60-180s)…</>
                : <><Play className="w-4 h-4" /> Run KYC</>
              }
            </button>
          </div>
        </section>

        {/* ── Outcome pill — TOP of result section ── */}
        {(latest || running) && (
          <motion.section
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            data-testid="kyc-outcome-top"
            className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-5 flex items-center justify-between gap-4 flex-wrap"
          >
            <div className="flex items-center gap-4 flex-wrap">
              <div data-testid="kyc-check-tier-top" className="flex flex-col">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">Check Tier</span>
                {tier ? (
                  <span className={`mt-1 text-base font-bold px-3 py-1 rounded-full border w-fit ${CHECK_COLORS[tier] || 'text-slate-300 border-slate-600'}`}>
                    {tier}
                  </span>
                ) : (
                  <Loader2 className="w-4 h-4 text-slate-500 animate-spin mt-1" />
                )}
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">Outcome</span>
                {latest ? (
                  <span
                    data-testid="kyc-outcome-pill"
                    className={`mt-1 text-2xl font-extrabold px-5 py-2 rounded-full border ${OUTCOME_COLORS[outcomeKey]}`}
                  >
                    {OUTCOME_LABEL[outcomeKey]}
                  </span>
                ) : <span className="text-slate-400 text-sm mt-1">—</span>}
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] uppercase tracking-wider text-slate-500">Action</span>
                <span
                  data-testid="kyc-outcome-action"
                  className={`mt-1 text-sm font-bold px-3 py-1 rounded-md ${
                    outcomeKey === 'positive' ? 'bg-emerald-600 text-white' :
                    outcomeKey === 'negative' ? 'bg-red-600 text-white' :
                    outcomeKey === 'positive_with_conditions' ? 'bg-amber-500 text-black' :
                    'bg-slate-700 text-slate-200'
                  }`}
                >
                  {OUTCOME_ACTION[outcomeKey]}
                </span>
              </div>
            </div>
            {latest && (
              <div className="flex items-center gap-2">
                <a
                  href={`/credit-risk/kyc/${latest.id}`}
                  className="px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-700 text-slate-200 text-xs flex items-center gap-1.5 hover:bg-slate-700"
                >
                  Open Detail <ChevronRight className="w-3 h-3" />
                </a>
                <button
                  onClick={() => exportPdf(latest.id, latest.counterparty?.name || 'kyc')}
                  data-testid="kyc-export-pdf"
                  className="px-4 py-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-emerald-600 text-white text-xs font-semibold flex items-center gap-1.5 hover:shadow-lg hover:shadow-cyan-500/20"
                >
                  <Printer className="w-3 h-3" /> Export KYC PDF
                </button>
              </div>
            )}
          </motion.section>
        )}

        {/* ── Tri-indicator scoring panel ── */}
        {(latest || running) && (
          <motion.section
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            data-testid="kyc-tri-indicator"
            className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-5 space-y-3"
          >
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <DollarSign className="w-4 h-4 text-emerald-400" /> Tri-Indicator Score
            </h2>
            <div className="grid grid-cols-5 gap-3">
              <ScoreCell label="Indicator I (CPI)" value={triI} caption={latest?.indicator_i?.rationale} testId="kyc-score-i" />
              <ScoreCell label="Indicator II (Notional)" value={triII} caption={latest?.indicator_ii?.rationale} testId="kyc-score-ii" />
              <ScoreCell label="Indicator III (Industry)" value={triIII} caption={latest?.indicator_iii?.rationale} testId="kyc-score-iii" />
              <ScoreCell
                label="Aggregated"
                value={typeof aggregated === 'number' ? Math.round(aggregated) : undefined}
                caption="Sum 15-75"
                big
                testId="kyc-score-aggregated"
              />
              <div data-testid="kyc-check-tier" className="bg-slate-900/60 border border-slate-700 rounded-xl p-3 flex flex-col items-center justify-center">
                <span className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">Check Tier</span>
                {tier ? (
                  <span className={`text-base font-bold px-3 py-1 rounded-full border ${CHECK_COLORS[tier] || 'text-slate-300 border-slate-600'}`}>
                    {tier}
                  </span>
                ) : (
                  <span className="text-slate-500 text-xs">—</span>
                )}
              </div>
            </div>
          </motion.section>
        )}

        {/* ── Intermediate checklist matrix ── */}
        {latest && matrixItems.length > 0 && (
          <motion.section
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            data-testid="kyc-checklist-matrix"
            className="bg-slate-800/30 border border-slate-700/50 rounded-2xl p-5 space-y-3"
          >
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-cyan-400" /> Intermediate Compliance Checks
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-xs" data-testid="kyc-checklist-table">
                <thead>
                  <tr className="text-left text-slate-400 border-b border-slate-700">
                    <th className="py-2 pr-3 font-medium">Item</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">L / M / H</th>
                    <th className="py-2 pr-3 font-medium">Comment</th>
                  </tr>
                </thead>
                <tbody>
                  {matrixItems.map((it, idx) => {
                    const label = it.label || it.name || it.item || '—';
                    const status = (it.status || it.outcome || '—').toUpperCase();
                    const risk = (it.risk_grade || it.risk || '').toUpperCase();
                    const statusKey = status === 'PASS' ? 'OK' : status;
                    const statusColor = STATUS_COLOR[statusKey] || 'text-slate-300';
                    return (
                      <tr
                        key={idx}
                        className="border-b border-slate-800/60"
                        data-testid="kyc-checklist-row"
                      >
                        <td className="py-2 pr-3 text-slate-200">{label}</td>
                        <td className={`py-2 pr-3 font-medium ${statusColor}`}>{status}</td>
                        <td className="py-2 pr-3">
                          <span className={`inline-block px-2 py-0.5 rounded border text-[11px] font-semibold ${RISK_BG[risk] || 'border-slate-700 text-slate-400'}`}>
                            {risk || '—'}
                          </span>
                        </td>
                        <td className="py-2 pr-3 text-slate-400">{it.comment || '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </motion.section>
        )}

        {/* ── Import existing PDF zone — demoted to secondary "or import" affordance ── */}
        <div
          data-testid="kyc-import-zone"
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={onDrop}
          className={`rounded-xl border border-dashed px-5 py-3 transition-colors ${
            dragActive
              ? 'border-cyan-400 bg-cyan-500/5'
              : 'border-slate-700/50 bg-slate-800/10'
          }`}
        >
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Upload className="w-4 h-4 text-slate-500" />
              <span>Or import from PDF — drop a MET-template KYC report and the agent will reconcile + queue for sign-off.</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                data-testid="kyc-import-input"
                type="file"
                multiple
                accept="application/pdf,.pdf"
                onChange={onPick}
                className="hidden"
              />
              <button
                data-testid="kyc-import-pick"
                onClick={() => fileInputRef.current?.click()}
                disabled={importing}
                className="text-xs text-cyan-400 hover:text-cyan-300 underline-offset-2 hover:underline disabled:opacity-50 flex items-center gap-1.5"
              >
                {importing ? (
                  <><Loader2 className="w-3 h-3 animate-spin" /> Processing…</>
                ) : (
                  <><FileText className="w-3 h-3" /> Choose PDF</>
                )}
              </button>
            </div>
          </div>
          {importError && (
            <div data-testid="kyc-import-error" className="mt-3 text-xs text-red-400 flex items-center gap-2">
              <XCircle className="w-3 h-3" /> {importError}
            </div>
          )}

          {duplicateBanners.length > 0 && (
            <div data-testid="kyc-duplicate-banner" className="mt-3 space-y-1.5">
              {duplicateBanners.map((d, i) => (
                <div key={i} className="flex items-center justify-between gap-3 text-xs px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-200">
                  <span>
                    Already imported <b>{d.filename}</b>
                    {d.imported_at ? ` on ${new Date(d.imported_at).toISOString().slice(0, 10)}` : ''}.
                  </span>
                  <a
                    href={`/credit-risk/kyc/${d.existing_kyc_id}`}
                    className="px-2 py-0.5 rounded border border-cyan-400/40 hover:bg-cyan-500/20"
                  >
                    View existing
                  </a>
                </div>
              ))}
            </div>
          )}

          {importQueue.length > 0 && (
            <div data-testid="kyc-import-queue" className="mt-4 bg-slate-900/40 border border-slate-700/40 rounded-lg overflow-hidden">
              <div className="px-3 py-2 text-[10px] uppercase tracking-wide text-slate-500 bg-slate-900/60">
                Import queue ({importQueue.length})
              </div>
              {importQueue.map((q, i) => {
                const badge =
                  q.status === 'done' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                  : q.status === 'failed' ? 'bg-red-500/20 text-red-300 border-red-500/40'
                  : q.status === 'duplicate' ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                  : q.status === 'processing' ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  : 'bg-slate-700/40 text-slate-300 border-slate-600';
                const latestStep = q.steps?.length ? q.steps[q.steps.length - 1].step : null;
                return (
                  <div
                    key={i}
                    data-testid={`kyc-import-queue-row-${i}`}
                    className="grid grid-cols-[1fr_140px_120px] items-center gap-3 px-3 py-2 border-t border-slate-800/60 text-xs"
                  >
                    <div className="truncate text-slate-200">{q.name}</div>
                    <div>
                      <span className={`inline-block px-2 py-0.5 rounded border text-[10px] uppercase ${badge}`}>
                        {q.status}
                      </span>
                      {latestStep && (
                        <span className="ml-2 text-[10px] text-slate-500">{latestStep}</span>
                      )}
                      {q.error && (
                        <span className="ml-2 text-[10px] text-red-400">{q.error}</span>
                      )}
                    </div>
                    <div className="text-right">
                      {q.row_id ? (
                        <a
                          data-testid={`kyc-import-queue-view-${i}`}
                          href={`/credit-risk/kyc/${q.row_id}`}
                          className="text-cyan-400 hover:text-cyan-300"
                        >
                          View
                        </a>
                      ) : <span className="text-slate-600">—</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Reconciliation report panel (preserved) */}
        {report && (
          <motion.div
            data-testid="kyc-reconciliation-panel"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-slate-800/40 border border-slate-700/60 rounded-2xl p-5 space-y-4"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white flex items-center gap-2">
                  <FileCheck2 className="w-4 h-4 text-emerald-400" /> Reconciliation report
                </p>
                <p className="text-xs text-slate-400">
                  Counterparty:{' '}
                  <span data-testid="kyc-extracted-name" className="text-white font-semibold">
                    {(() => {
                      const nm = intermediateUnwrap(report.reconciled_record?.counterparty?.name)
                        ?? intermediateUnwrap(report.extracted?.counterparty?.name);
                      return (typeof nm === 'string' && nm) ? nm : '—';
                    })()}
                  </span>
                  {(() => {
                    const oc = intermediateUnwrap(report.reconciled_record?.outcome_of_check);
                    if (!oc || typeof oc !== 'string') return null;
                    return (
                      <>
                        {' '}• Outcome:{' '}
                        <span
                          data-testid="kyc-extracted-outcome"
                          className={`inline-block px-2 py-0.5 rounded text-[10px] uppercase border ${OUTCOME_COLORS[oc] || ''}`}
                        >
                          {oc}
                        </span>
                      </>
                    );
                  })()}
                  {originalPdfUrl && (
                    <a
                      data-testid="kyc-pdf-link"
                      href={`${API_URL}${originalPdfUrl}`}
                      target="_blank"
                      rel="noopener"
                      className="ml-2 text-cyan-400 hover:text-cyan-300 inline-flex items-center gap-1 text-xs"
                    >
                      <Download className="w-3 h-3" /> original PDF
                    </a>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {dirty && (
                  <button
                    data-testid="kyc-save-edits-btn"
                    disabled={savingEdit}
                    onClick={savePendingEdits}
                    className="px-3 py-2 rounded-lg bg-cyan-500/20 border border-cyan-500/40 text-cyan-300 text-xs font-semibold hover:bg-cyan-500/30 disabled:opacity-50"
                  >
                    {savingEdit ? 'Saving…' : 'Save edits'}
                  </button>
                )}
                <button
                  data-testid="kyc-discard-btn"
                  onClick={discardImport}
                  className="px-3 py-2 rounded-lg bg-slate-700/40 border border-slate-600 text-slate-300 text-xs font-semibold hover:bg-slate-700/60 flex items-center gap-1.5"
                >
                  <XCircle className="w-3 h-3" /> Discard
                </button>
                {canAutoSignOff ? (
                  <button
                    data-testid="kyc-sign-off-btn"
                    disabled={dirty}
                    onClick={() => signOffImported(false)}
                    className="px-4 py-2 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-sm font-semibold hover:bg-emerald-500/30 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    title={dirty ? 'Save edits first' : 'Approve and sign off'}
                  >
                    <CheckCircle2 className="w-4 h-4" /> Save & sign off
                  </button>
                ) : (
                  <button
                    data-testid="kyc-human-review-btn"
                    onClick={() => setShowHumanReviewReason(true)}
                    className="px-4 py-2 rounded-lg bg-amber-500/20 border border-amber-500/40 text-amber-300 text-sm font-semibold hover:bg-amber-500/30 flex items-center gap-2"
                  >
                    <AlertTriangle className="w-4 h-4" /> Send for human review
                  </button>
                )}
              </div>
            </div>

            <div data-testid="kyc-validations-table" className="bg-slate-900/40 border border-slate-700/40 rounded-lg overflow-hidden">
              <div className="grid grid-cols-12 text-[10px] uppercase tracking-wide text-slate-500 bg-slate-900/60 px-3 py-2">
                <div className="col-span-4">Field</div>
                <div className="col-span-2">Status</div>
                <div className="col-span-6">Note</div>
              </div>
              {(report.validations || []).map((v, i) => (
                <div
                  key={i}
                  data-testid={`kyc-validation-row-${i}`}
                  className="grid grid-cols-12 text-xs px-3 py-2 border-t border-slate-800/60"
                >
                  <div className="col-span-4 text-slate-300 truncate">{String(v.field ?? '')}</div>
                  <div className="col-span-2">
                    <span className={`inline-block px-2 py-0.5 rounded border text-[10px] uppercase ${VALIDATION_BADGE[v.status] || 'text-slate-400 bg-slate-500/10 border-slate-500/30'}`}>
                      {String(v.status ?? '')}
                    </span>
                  </div>
                  <div className="col-span-6 text-slate-400 truncate">{String(v.note ?? '')}</div>
                </div>
              ))}
            </div>

            {/* Inline-editable header fields */}
            <div data-testid="kyc-inline-edit-grid" className="grid grid-cols-2 gap-3 text-xs">
              <label className="block text-slate-400">
                Counterparty name
                <input
                  data-testid="kyc-edit-name"
                  value={edits.counterparty_name ?? (intermediateUnwrap(report.reconciled_record?.counterparty?.name) || '')}
                  onChange={e => setEdits(s => ({ ...s, counterparty_name: e.target.value }))}
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-white"
                />
              </label>
              <label className="block text-slate-400">
                Country ISO-2
                <input
                  data-testid="kyc-edit-country"
                  maxLength={2}
                  value={edits.country_iso2 ?? (intermediateUnwrap(report.reconciled_record?.counterparty?.country_iso2) || '')}
                  onChange={e => setEdits(s => ({ ...s, country_iso2: e.target.value.toUpperCase() }))}
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-white uppercase"
                />
              </label>
              <label className="block text-slate-400">
                Type of check
                <select
                  data-testid="kyc-edit-type-of-check"
                  value={edits.type_of_check ?? (intermediateUnwrap(report.reconciled_record?.type_of_check) || '')}
                  onChange={e => setEdits(s => ({ ...s, type_of_check: e.target.value }))}
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-white"
                >
                  <option value="">—</option>
                  <option value="Simplified">Simplified</option>
                  <option value="Standard">Standard</option>
                  <option value="Enhanced">Enhanced</option>
                  <option value="Special">Special</option>
                </select>
              </label>
              <label className="block text-slate-400">
                Outcome
                <select
                  data-testid="kyc-edit-outcome"
                  value={edits.outcome_of_check ?? (intermediateUnwrap(report.reconciled_record?.outcome_of_check) || '')}
                  onChange={e => setEdits(s => ({ ...s, outcome_of_check: e.target.value }))}
                  className="mt-1 w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-white"
                >
                  <option value="">—</option>
                  <option value="positive">positive</option>
                  <option value="positive_with_conditions">positive_with_conditions</option>
                  <option value="negative">negative</option>
                  <option value="needs_review">needs_review</option>
                  <option value="pending">pending</option>
                </select>
              </label>
            </div>

            {Array.isArray(report.reconciled_record?.intermediate_checks) && report.reconciled_record.intermediate_checks.length > 0 && (
              <div data-testid="kyc-intermediate-checks" className="bg-slate-900/40 border border-slate-700/40 rounded-lg overflow-hidden">
                <div className="px-3 py-2 text-[10px] uppercase tracking-wide text-slate-500 bg-slate-900/60">
                  Intermediate checks ({report.reconciled_record.intermediate_checks.length})
                </div>
                {report.reconciled_record.intermediate_checks.map((c: any, i: number) => {
                  // Controlled values. When the extractor couldn't determine a
                  // grade/outcome we render an explicit "—" placeholder; the
                  // officer must consciously pick one before sign-off enables.
                  const rawRisk = intermediateUnwrap(c.risk_grade);
                  const rawRiskAlt = intermediateUnwrap(c.risk);
                  const riskV = (rawRisk || rawRiskAlt || '') as string;
                  const rawStatus = intermediateUnwrap(c.status);
                  const rawOutcome = intermediateUnwrap(c.outcome);
                  const statusV = (rawStatus || rawOutcome || '') as string;
                  return (
                    <div
                      key={i}
                      data-testid={`kyc-int-check-${i}`}
                      className="grid grid-cols-12 text-xs px-3 py-2 border-t border-slate-800/60 items-center"
                    >
                      <div className="col-span-6 text-slate-300 truncate">{String(c.label || c.item || c.name || '')}</div>
                      <div className="col-span-3">
                        <select
                          data-testid={`kyc-int-status-edit-${i}`}
                          value={statusV}
                          onChange={e => {
                            const v = e.target.value;
                            const next = [...(report.reconciled_record.intermediate_checks || [])];
                            next[i] = { ...next[i], status: v || null, outcome: v || null };
                            setEdits(s => ({ ...s, intermediate_checks: next }));
                            // Mirror into report so the controlled select re-renders.
                            setReport(prev => prev ? ({
                              ...prev,
                              reconciled_record: { ...prev.reconciled_record, intermediate_checks: next },
                            }) : prev);
                          }}
                          className="w-full bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-slate-200 text-[11px]"
                        >
                          <option value="">—</option>
                          <option value="ok">ok</option>
                          <option value="fail">fail</option>
                          <option value="n/a">n/a</option>
                        </select>
                      </div>
                      <div className="col-span-3">
                        <select
                          data-testid={`kyc-int-risk-edit-${i}`}
                          value={riskV}
                          onChange={e => {
                            const v = e.target.value;
                            const next = [...(report.reconciled_record.intermediate_checks || [])];
                            next[i] = { ...next[i], risk_grade: v || null, risk: v || null };
                            setEdits(s => ({ ...s, intermediate_checks: next }));
                            // Mirror into report so the controlled select re-renders.
                            setReport(prev => prev ? ({
                              ...prev,
                              reconciled_record: { ...prev.reconciled_record, intermediate_checks: next },
                            }) : prev);
                          }}
                          className={`w-full bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5 text-[11px] ${
                            riskV === 'H' ? 'text-red-300' : riskV === 'M' ? 'text-amber-300' : riskV === 'L' ? 'text-emerald-300' : 'text-slate-400'
                          }`}
                        >
                          <option value="">—</option>
                          <option value="L">L</option>
                          <option value="M">M</option>
                          <option value="H">H</option>
                        </select>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Expanded reconciliation sections so officer can review every persisted field */}
            <details data-testid="kyc-rec-section-identity" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">Identity</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(report.reconciled_record?.counterparty || {}, null, 2)}</pre>
            </details>
            <details data-testid="kyc-rec-section-sanctions" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">Sanctions</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify({
                sanctions_applicable: report.reconciled_record?.sanctions_applicable,
                sanctions_pre_screen: report.extracted?.sanctions_pre_screen,
              }, null, 2)}</pre>
            </details>
            <details data-testid="kyc-rec-section-triindicator" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">Tri-Indicator</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify({
                indicator_i: report.reconciled_record?.indicator_i,
                indicator_ii: report.reconciled_record?.indicator_ii,
                indicator_iii: report.reconciled_record?.indicator_iii,
                aggregated_score: report.reconciled_record?.aggregated_score,
                type_of_check: report.reconciled_record?.type_of_check,
              }, null, 2)}</pre>
            </details>
            <details data-testid="kyc-rec-section-compliance" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">Compliance Checks</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(report.reconciled_record?.basic_compliance || {}, null, 2)}</pre>
            </details>
            <details data-testid="kyc-rec-section-page2" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">Page 2 — Sign-off / Moody's / Comments</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify({
                shareholder_structure_summary: report.reconciled_record?.shareholder_structure_summary,
                summary_of_compliance_risk_assessment: report.reconciled_record?.summary_of_compliance_risk_assessment,
                general_comments: report.reconciled_record?.general_comments,
                legal_consulted: report.reconciled_record?.legal_consulted,
                outcome_of_check: report.reconciled_record?.outcome_of_check,
                supporting_docs_location: report.reconciled_record?.supporting_docs_location,
                local_kyc_expert_name: report.reconciled_record?.local_kyc_expert_name,
              }, null, 2)}</pre>
            </details>
            <details data-testid="kyc-rec-section-ubos" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">UBOs</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(report.reconciled_record?.ubos || [], null, 2)}</pre>
            </details>
            <details data-testid="kyc-rec-section-gaps" className="bg-slate-900/30 border border-slate-700/40 rounded-lg">
              <summary className="px-3 py-2 text-xs font-semibold text-slate-200 cursor-pointer">Discovery Gaps ({(report.reconciled_record?.discovery_gaps || []).length})</summary>
              <pre className="text-[10px] text-slate-400 px-3 pb-3 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(report.reconciled_record?.discovery_gaps || [], null, 2)}</pre>
            </details>

            {showHumanReviewReason && (
              <div data-testid="kyc-human-review-modal" className="bg-amber-500/5 border border-amber-500/30 rounded-lg p-3 space-y-2">
                <div className="text-xs text-amber-300 font-semibold flex items-center gap-2">
                  <AlertTriangle className="w-3 h-3" /> Reason for human review
                </div>
                <textarea
                  data-testid="kyc-human-review-reason"
                  value={humanReviewReason}
                  onChange={e => setHumanReviewReason(e.target.value)}
                  placeholder="What needs a senior reviewer's attention?"
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-xs text-white"
                  rows={3}
                />
                <div className="flex justify-end gap-2">
                  <button
                    onClick={() => { setShowHumanReviewReason(false); setHumanReviewReason(''); }}
                    className="px-3 py-1.5 rounded text-xs text-slate-400 hover:text-slate-200"
                  >
                    Cancel
                  </button>
                  <button
                    data-testid="kyc-human-review-submit"
                    disabled={!humanReviewReason.trim()}
                    onClick={() => signOffImported(true)}
                    className="px-3 py-1.5 rounded bg-amber-500/20 border border-amber-500/40 text-amber-300 text-xs font-semibold hover:bg-amber-500/30 disabled:opacity-50"
                  >
                    Park as NEEDS REVIEW
                  </button>
                </div>
              </div>
            )}
          </motion.div>
        )}

        {/* KPI strip — 3 headline KPIs, sub-line carries Signed / Enhanced detail */}
        <div className="grid grid-cols-3 gap-4">
          {[
            {
              label: 'Total Checks',
              value: counts.total,
              icon: FileCheck2,
              color: 'text-cyan-400',
              sub: counts.enhanced > 0 ? `${counts.enhanced} Enhanced / Special` : null,
            },
            {
              label: 'In Progress',
              value: counts.running,
              icon: Loader2,
              color: 'text-amber-400',
              sub: null,
            },
            {
              label: 'Completed',
              value: counts.completed,
              icon: CheckCircle2,
              color: 'text-emerald-400',
              sub: counts.signed > 0 ? `${counts.signed} signed off` : null,
            },
          ].map(kpi => (
            <div key={kpi.label} className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-2">
                <kpi.icon className={`w-4 h-4 ${kpi.color}`} />
                <span className="text-xs text-slate-400">{kpi.label}</span>
              </div>
              <p className={`text-2xl font-bold ${kpi.color}`}>{kpi.value}</p>
              {kpi.sub && <p className="text-[10px] text-slate-500 mt-1">{kpi.sub}</p>}
            </div>
          ))}
        </div>

        {/* Check list */}
        {checks.length === 0 ? (
          <div className="text-center py-16 bg-slate-800/20 border border-slate-700/40 rounded-2xl">
            <FileCheck2 className="w-12 h-12 text-slate-700 mx-auto mb-3" />
            <p className="text-slate-400 mb-2 text-sm">No KYC checks yet — fill the form above to start.</p>
          </div>
        ) : (
          <div data-testid="kyc-list" className="space-y-2">
            <div className="flex items-center justify-between mt-4 mb-1">
              <h3 className="text-xs uppercase tracking-wider text-slate-500">Recent KYC checks</h3>
              <button
                data-testid="kyc-filter-imported"
                onClick={() => setFilterImported(v => !v)}
                className={`text-[10px] px-2 py-0.5 rounded-full border uppercase ${
                  filterImported
                    ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
                    : 'border-slate-700 text-slate-400 hover:border-slate-500'
                }`}
              >
                {filterImported ? 'Showing imported only' : 'Imported only'}
              </button>
            </div>
            {(filterImported
              ? checks.filter(c => c.raw_agent_response?.source === 'imported_pdf')
              : checks
            ).slice(0, 20).map((c) => {
              const checkType = c.type_of_check || 'Pending';
              const checkColor = CHECK_COLORS[checkType] || 'text-slate-400 bg-slate-500/10 border-slate-500/30';
              const oc = (c.outcome_of_check || '').toLowerCase();
              const ocKey = ['positive', 'positive_with_conditions', 'negative', 'pending'].includes(oc) ? oc : '';
              const ocColor = ocKey ? OUTCOME_COLORS[ocKey] : '';
              const isImported = c.raw_agent_response?.source === 'imported_pdf';
              const nrd = c.next_review_due ? new Date(c.next_review_due) : null;
              let nrdClass = 'text-slate-400';
              let nrdLabel = nrd ? nrd.toISOString().slice(0,10) : '—';
              if (nrd) {
                if (nrd < today) nrdClass = 'text-red-400 font-semibold';
                else if (nrd < ninetyDays) nrdClass = 'text-amber-400 font-semibold';
              }
              return (
                <motion.a
                  key={c.id}
                  data-testid={`kyc-row-${c.id}`}
                  href={`/credit-risk/kyc/${c.id}`}
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="block bg-slate-800/30 border border-slate-700/50 rounded-xl p-3 hover:border-cyan-500/50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-cyan-500/10 to-emerald-500/10 border border-cyan-500/20 flex items-center justify-center shrink-0">
                      {c.status === 'running' && <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />}
                      {c.status === 'completed' && !c.signed_at && <FileCheck2 className="w-4 h-4 text-cyan-400" />}
                      {c.signed_at && <ShieldCheck className="w-4 h-4 text-emerald-400" />}
                      {c.status === 'failed' && <XCircle className="w-4 h-4 text-red-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-white truncate">{c.counterparty?.name || '(no name)'}</span>
                        {isImported && (
                          <span data-testid="kyc-imported-badge" className="text-[10px] px-2 py-0.5 rounded-full border border-cyan-500/40 text-cyan-300 bg-cyan-500/10 uppercase">
                            imported
                          </span>
                        )}
                        {c.counterparty?.country_iso2 && (
                          <span className="text-[10px] text-slate-400 flex items-center gap-1">
                            <Flag className="w-3 h-3" /> {c.counterparty.country_iso2}
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-slate-400">
                        {c.activity_trigger && <span>{c.activity_trigger}</span>}
                        {c.type_of_business_relationship && <span>· {c.type_of_business_relationship}</span>}
                        {c.aggregated_score != null && <span>· Score {c.aggregated_score.toFixed(0)}</span>}
                        {c.created_at && <span>· {new Date(c.created_at).toLocaleDateString()}</span>}
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1 text-right">
                      <span data-testid={`kyc-next-review-${c.id}`} className={`text-[10px] uppercase tracking-wider ${nrdClass}`}>
                        Next review: {nrdLabel}
                      </span>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-2 py-1 rounded-full border ${checkColor}`}>{checkType}</span>
                        {ocKey && <span className={`text-xs px-2 py-1 rounded-full border ${ocColor}`}>{OUTCOME_LABEL[ocKey]}</span>}
                        <ChevronRight className="w-4 h-4 text-slate-600" />
                      </div>
                    </div>
                  </div>
                </motion.a>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function ScoreCell({ label, value, caption, big, testId }: { label: string; value?: number; caption?: string; big?: boolean; testId?: string }) {
  return (
    <div
      data-testid={testId}
      className="bg-slate-900/60 border border-slate-700 rounded-xl p-3 flex flex-col items-center justify-center text-center"
    >
      <span className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</span>
      <span className={`${big ? 'text-3xl' : 'text-2xl'} font-bold text-white`}>
        {value != null ? value : <Loader2 className="w-4 h-4 text-slate-500 animate-spin" />}
      </span>
      {caption && <span className="text-[10px] text-slate-500 mt-1 line-clamp-2">{caption}</span>}
    </div>
  );
}
