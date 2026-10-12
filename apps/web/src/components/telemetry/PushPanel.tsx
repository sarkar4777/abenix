'use client';

import { useState } from 'react';
import { CheckCircle2, Copy, KeyRound, Loader2, Send, XCircle } from 'lucide-react';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { API_URL, apiFetch } from '@/lib/api-client';
import { explainTelemetryError } from '@/lib/telemetry/errors';
import { pushSnippets, pushSubject, withSubject, type Mapping } from '@/lib/telemetry/sources';
import { ingestError, testMessageError } from '@/lib/telemetry/keys';
import { useKept } from '@/lib/telemetry/kept';

type Lang = 'curl' | 'python' | 'js';
const LANGS: { id: Lang; label: string }[] = [{ id: 'curl', label: 'curl' }, { id: 'python', label: 'Python' }, { id: 'js', label: 'JavaScript' }];

export function ingestEndpoint(sourceId: string | null, ingestUrl?: string | null): string {
  if (ingestUrl) return /^https?:\/\//.test(ingestUrl) ? ingestUrl : `${API_URL}${ingestUrl}`;
  return `${API_URL}/api/telemetry/ingest/${sourceId ?? '<source id>'}`;
}

function CopyButton({ text, label, testId }: { text: string; label: string; testId?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {}); }}
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
      data-testid={testId}
    >
      {done ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" /> : <Copy className="h-3.5 w-3.5" />} {done ? 'Copied' : label}
    </button>
  );
}

// where another system sends its data, the token once, and code to paste
export default function PushPanel({ sourceId, token: firstToken, ingestUrl, onSent, testBody, mapping }: { sourceId: string | null; token: string | null; ingestUrl?: string | null; onSent?: (sample: string) => void; testBody?: string; mapping?: Partial<Mapping> | null }) {
  const [token, setToken] = useKept<string | null>(`push:${sourceId}:token`, firstToken);
  const [lang, setLang] = useState<Lang>('curl');
  const [rotating, setRotating] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [rotateErr, setRotateErr] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const endpoint = ingestEndpoint(sourceId, ingestUrl);
  const snip = pushSnippets(endpoint, token ?? '', { sample: testBody, mapping });

  async function rotate() {
    if (!sourceId) return;
    setRotating(true);
    setRotateErr(null);
    try {
      const res = await apiFetch<{ token?: string; ingest_token?: string }>(`/api/telemetry/connections/${sourceId}/token`, { method: 'POST' });
      setToken(res.data?.ingest_token ?? res.data?.token ?? null);
      setConfirmRotate(false);
    } catch (e) {
      setRotateErr(explainTelemetryError(e, 'save'));
    } finally {
      setRotating(false);
    }
  }

  function testSample(): string {
    let sample = JSON.stringify({ asset: 'test-asset', temperature_c: 21.5, pressure_bar: 1.01, ts: Date.now() });
    if (testBody) { try { sample = JSON.stringify(JSON.parse(testBody)); } catch { /* keep the generic one */ } }
    return sample;
  }

  // through the token, for an older server without the test endpoint
  async function sendWithToken(sample: string, subject: string): Promise<{ ok: boolean; text: string }> {
    const res = await fetch(withSubject(endpoint, subject), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', 'Idempotency-Key': `test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` },
      body: sample,
    });
    if (res.ok) return { ok: true, text: 'Accepted. It shows under Messages straight away, and on the Assets tab once the mapping places it.' };
    const body = await res.json().catch(() => null);
    return { ok: false, text: ingestError(res.status, body?.error?.error_code) };
  }

  async function sendTest() {
    if (!sourceId) return;
    setSending(true);
    setResult(null);
    const sample = testSample();
    const subject = pushSubject(mapping) ?? 'test/test-device';
    try {
      const res = await apiFetch<{ stored?: boolean; group?: string; node?: string; device?: string; message?: string }>(
        `/api/telemetry/connections/${sourceId}/test-message`,
        { method: 'POST', body: JSON.stringify({ payload: sample, subject }), silent: true, throwOnError: false },
      );
      let out: { ok: boolean; text: string };
      if ((res.errorDetail?.code === 404 || res.errorDetail?.code === 405) && token) {
        out = await sendWithToken(sample, subject);
      } else if (res.error) {
        out = { ok: false, text: testMessageError(res.errorDetail?.code ?? 0, res.errorDetail?.error_code, res.error) };
      } else {
        const d = res.data || {};
        const where = d.node ? `${d.group ? `${d.group} / ` : ''}${d.node}${d.device ? ` / ${d.device}` : ''}` : null;
        out = d.stored === false
          ? { ok: false, text: d.message || 'It arrived but was not stored, the mapping does not place it yet. Set up the mapping next, Messages, Problems also says why.' }
          : { ok: true, text: d.message || (where ? `Stored as ${where}. It shows on the Assets tab now.` : 'Accepted. It shows under Messages straight away, and on the Assets tab once the mapping places it.') };
      }
      setResult(out);
      // it arrived even when the mapping did not place it, so the mapping step gets the sample
      if (out.ok || (!res.error && res.data)) onSent?.(JSON.stringify(JSON.parse(sample), null, 2));
    } catch {
      setResult({ ok: false, text: ingestError(0) });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-3" data-testid="tel-push">
      <p className="text-sm text-slate-300">Any system can send data here over HTTPS. JSON, one JSON per line, CSV and plain text all work. Each request needs the token below.</p>
      <div>
        <p className="mb-1 text-xs font-medium text-slate-300">Endpoint</p>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 break-all rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-cyan-200" data-testid="tel-push-endpoint">POST {endpoint}</code>
          <CopyButton text={endpoint} label="Copy" />
        </div>
      </div>
      <div>
        <p className="mb-1 text-xs font-medium text-slate-300">Token</p>
        {token ? (
          <>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded-md border border-amber-500/40 bg-amber-500/5 px-2.5 py-2 text-xs text-amber-100" data-testid="tel-push-token">{token}</code>
              <CopyButton text={token} label="Copy" testId="tel-push-token-copy" />
            </div>
            <p className="mt-1 text-xs text-amber-200">Copy it now. It is shown this once and stored only as a hash.</p>
          </>
        ) : (
          <p className="text-xs text-slate-400">The token was shown once, when it was made. If it is lost, rotate it to get a new one.</p>
        )}
        {sourceId && (
          <button type="button" onClick={() => setConfirmRotate(true)} className="mt-2 inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" data-testid="tel-push-rotate">
            <KeyRound className="h-3.5 w-3.5" /> {token ? 'Rotate the token' : 'Get a new token'}
          </button>
        )}
      </div>
      <div>
        <div className="mb-1 flex items-center gap-1" role="tablist" aria-label="Code">
          {LANGS.map((l) => (
            <button key={l.id} type="button" role="tab" aria-selected={lang === l.id} onClick={() => setLang(l.id)} className={`rounded-md px-2 py-1 text-xs ${lang === l.id ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-white'}`} data-testid={`tel-push-lang-${l.id}`}>{l.label}</button>
          ))}
          <span className="flex-1" />
          <CopyButton text={snip[lang]} label="Copy code" testId="tel-push-copy-code" />
        </div>
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border border-slate-700 bg-slate-950 p-2.5 font-mono text-[11px] text-slate-200" data-testid="tel-push-snippet">{snip[lang]}</pre>
      </div>
      <button type="button" onClick={sendTest} disabled={!sourceId || sending} className="inline-flex min-h-[38px] items-center gap-1.5 rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="tel-push-test">
        {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send a test message
      </button>
      {result && (
        <p className={`flex items-start gap-1.5 rounded-lg border px-3 py-2 text-sm ${result.ok ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-100' : 'border-rose-500/30 bg-rose-500/5 text-rose-100'}`} role="status" data-testid="tel-push-result">
          {result.ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0" />} {result.text}
        </p>
      )}
      {confirmRotate && (
        <ConfirmModal
          open
          onClose={() => !rotating && setConfirmRotate(false)}
          onConfirm={rotate}
          loading={rotating}
          variant="warning"
          icon={KeyRound}
          title="Rotate the token?"
          description="A new token is made and the old one stops working at once. Any system still sending with the old token is refused until it is given the new one. This is recorded in the audit log."
          confirmLabel="Rotate the token"
          confirmTestId="tel-push-rotate-confirm"
        >
          {rotateErr && <p className="text-xs text-rose-300" role="alert">{rotateErr}</p>}
        </ConfirmModal>
      )}
    </div>
  );
}
