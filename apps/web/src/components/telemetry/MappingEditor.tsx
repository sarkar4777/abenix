'use client';

import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Loader2, Plus, Radio, Sparkles, Trash2 } from 'lucide-react';
import { apiFetch } from '@/lib/api-client';
import { CAPTURE_SECONDS, captureReason, explainTelemetryError } from '@/lib/telemetry/errors';
import { formatValue } from '@/lib/telemetry/format';
import { BLANK_MAPPING, cleanFilter, localSuggest, rulesToText, splitList, textToRules, type Mapping, type PreviewResult, type TsFormat } from '@/lib/telemetry/sources';

const FORMATS: { id: TsFormat; label: string }[] = [
  { id: 'auto', label: 'Work it out' },
  { id: 'epoch_s', label: 'Seconds since 1970' },
  { id: 'epoch_ms', label: 'Milliseconds since 1970' },
  { id: 'epoch_us', label: 'Microseconds since 1970' },
  { id: 'epoch_ns', label: 'Nanoseconds since 1970' },
  { id: 'iso', label: 'Date and time text (ISO 8601)' },
];

export function mappingProblems(m: Mapping): Record<string, string> {
  const out: Record<string, string> = {};
  for (const t of [m.group, m.node, m.device, m.event?.name ?? '']) {
    for (const tok of (t || '').match(/\{[^{}]*\}/g) || []) {
      if (!/^\{(subject(\.\d+)?|header\.[\w-]+|\$[^{}]*)\}$/.test(tok)) {
        out.templates = `${tok} is not something Abenix can fill in. Curly brackets take {subject.N} for part N of the topic, {header.name} for a header, or {$.path} for a value in the message.`;
      }
    }
  }
  for (const p of [m.timestamp.path, m.records ?? '', ...m.signals.include, ...m.signals.exclude]) {
    if (p && /\s/.test(p.trim())) out.paths = `"${p}" has a space in it. Paths look like $.engine.temp.`;
  }
  return out;
}

function Row({ label, hint, children, problem }: { label: string; hint?: string; children: React.ReactNode; problem?: string }) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-300">{label}</p>
      {children}
      {problem ? <p className="mt-1 text-xs text-rose-300" role="alert">{problem}</p> : hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}

export default function MappingEditor({
  sourceId, decoder, mapping, onChange, sample: initialSample = '', subject: initialSubject = '', showProblems,
}: {
  sourceId: string | null; decoder: string; mapping: Mapping; onChange: (m: Mapping) => void; sample?: string; subject?: string; showProblems?: boolean;
}) {
  const [sample, setSample] = useState(initialSample);
  const [subject, setSubject] = useState(initialSubject);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [busy, setBusy] = useState<'preview' | 'capture' | 'suggest' | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [unitPath, setUnitPath] = useState('');
  const [matchText, setMatchText] = useState(() => rulesToText(mapping.filter?.match));
  const [excludeText, setExcludeText] = useState(() => rulesToText(mapping.filter?.exclude));
  const [suggestNote, setSuggestNote] = useState<string | null>(null);
  const matchParsed = textToRules(matchText);
  const excludeParsed = textToRules(excludeText);
  const setFilter = (patch: { require?: string[]; matchText?: string; excludeText?: string }) => {
    const mt = patch.matchText ?? matchText;
    const et = patch.excludeText ?? excludeText;
    if (patch.matchText !== undefined) setMatchText(mt);
    if (patch.excludeText !== undefined) setExcludeText(et);
    const mp = textToRules(mt);
    const ep = textToRules(et);
    onChange({ ...m, filter: cleanFilter({ require: patch.require ?? m.filter?.require ?? [], match: mp.problem ? m.filter?.match : mp.rules, exclude: ep.problem ? m.filter?.exclude : ep.rules }) });
  };
  const [unitText, setUnitText] = useState('');
  const seq = useRef(0);
  const m = mapping;
  const set = (patch: Partial<Mapping>) => onChange({ ...m, ...patch });
  const problems = mappingProblems(m);
  const inputCls = 'w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-sm text-white placeholder:text-slate-600';

  // the preview follows every change, a moment after typing stops
  useEffect(() => {
    if (!sourceId || !sample.trim()) { setPreview(null); return; }
    const n = ++seq.current;
    const t = setTimeout(async () => {
      setBusy('preview');
      try {
        const res = await apiFetch<PreviewResult>(`/api/telemetry/connections/${sourceId}/preview`, { method: 'POST', body: JSON.stringify({ payload: sample, subject: subject || undefined, mapping: m, decoder }) });
        if (n !== seq.current) return;
        setPreview({ records: res.data?.records ?? [], errors: res.data?.errors ?? [], skipped: res.data?.skipped, skip_reason: res.data?.skip_reason });
        setErr(null);
      } catch (e) {
        if (n === seq.current) setErr(explainTelemetryError(e, 'load'));
      } finally {
        if (n === seq.current) setBusy(null);
      }
    }, 500);
    return () => clearTimeout(t);
  }, [sourceId, sample, subject, m, decoder]);

  const [capLeft, setCapLeft] = useState<number | null>(null);
  const [capErr, setCapErr] = useState<string | null>(null);
  const capAbort = useRef<AbortController | null>(null);
  useEffect(() => () => capAbort.current?.abort(), []);
  useEffect(() => {
    if (capLeft === null || capLeft <= 0) return;
    const t = setTimeout(() => setCapLeft((n) => (n === null ? n : n - 1)), 1000);
    return () => clearTimeout(t);
  }, [capLeft]);

  function cancelCapture() {
    capAbort.current?.abort();
    capAbort.current = null;
    setCapLeft(null);
    setBusy(null);
  }

  async function capture() {
    if (!sourceId) return;
    capAbort.current?.abort();
    const ctl = new AbortController();
    capAbort.current = ctl;
    // the server gives up at 20 s, this is the backstop if it never answers
    const backstop = setTimeout(() => ctl.abort(), (CAPTURE_SECONDS + 5) * 1000);
    setBusy('capture');
    setErr(null);
    setCapErr(null);
    setCapLeft(CAPTURE_SECONDS);
    try {
      const res = await apiFetch<PreviewResult & { sample?: { payload?: string; encoding?: string; subject?: string } | string }>(`/api/telemetry/connections/${sourceId}/preview`, { method: 'POST', body: JSON.stringify({ capture: true, mapping: m, decoder }), signal: ctl.signal, throwOnError: false, silent: true });
      if (ctl.signal.aborted) return;
      if (res.error) {
        setCapErr(captureReason({ status: res.errorDetail?.code, code: res.errorDetail?.error_code, message: res.error }));
        return;
      }
      const got = res.data?.sample;
      if (typeof got === 'string') setSample(got);
      else if (got?.payload !== undefined) {
        let text = got.payload;
        try { text = JSON.stringify(JSON.parse(got.payload), null, 2); } catch { /* not JSON, keep it as it came */ }
        setSample(text);
        if (got.subject) setSubject(got.subject);
      }
      setPreview({ records: res.data?.records ?? [], errors: res.data?.errors ?? [], skipped: res.data?.skipped, skip_reason: res.data?.skip_reason });
    } catch (e) {
      if (capAbort.current === ctl && ctl.signal.aborted) setCapErr(captureReason({ code: 'CAPTURE_TIMEOUT' }));
      else if (!ctl.signal.aborted) setCapErr(captureReason(e));
    } finally {
      clearTimeout(backstop);
      if (capAbort.current === ctl) {
        capAbort.current = null;
        setCapLeft(null);
        setBusy(null);
      }
    }
  }

  async function suggest() {
    setBusy('suggest');
    setErr(null);
    try {
      const res = await apiFetch<{ mapping?: Mapping; note?: string; reason?: string; filter_reason?: string; reasons?: Record<string, string> } & Partial<Mapping>>('/api/telemetry/mapping/suggest', { method: 'POST', body: JSON.stringify({ payload: sample, subject: subject || undefined, decoder }) });
      const got = res.data?.mapping ?? (res.data as Partial<Mapping> | null);
      if (got) {
        onChange({ ...BLANK_MAPPING, ...m, ...got, timestamp: { ...m.timestamp, ...(got.timestamp ?? {}) }, signals: { ...m.signals, ...(got.signals ?? {}) } });
        if (got.filter) { setMatchText(rulesToText(got.filter.match)); setExcludeText(rulesToText(got.filter.exclude)); }
        const why = res.data?.filter_reason ?? res.data?.reasons?.filter ?? res.data?.reason ?? res.data?.note;
        setSuggestNote(got.filter?.require?.length
          ? `Suggested a filter: only messages that have ${got.filter.require.join(' and ')} are kept.${why ? ` ${why}` : ''}`
          : why ?? null);
      }
    } catch {
      const local = localSuggest(sample);
      if (local) onChange({ ...m, ...local, signals: { ...m.signals, ...(local.signals ?? {}) }, timestamp: { ...m.timestamp, ...(local.timestamp ?? {}) } });
      else setErr('Could not suggest a mapping for this sample. Fill in the asset and the signals by hand.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-2" data-testid="tel-mapping">
      <div className="min-w-0 space-y-3">
        <div>
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <p className="flex-1 text-xs font-medium text-slate-300">A sample message</p>
            {sourceId && (capLeft !== null ? (
              <span className="inline-flex items-center gap-2 text-xs text-slate-300" role="status" data-testid="tel-map-capturing">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Waiting for the next message{capLeft !== null && capLeft > 0 ? `, ${capLeft} s` : ''}
                <button type="button" onClick={cancelCapture} className="rounded-md border border-slate-700 px-2 py-0.5 text-slate-200 hover:bg-slate-800" data-testid="tel-map-capture-cancel">Cancel</button>
              </span>
            ) : (
              <button type="button" onClick={capture} className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800" data-testid="tel-map-capture">
                <Radio className="h-3.5 w-3.5" /> Capture a live message
              </button>
            ))}
            <button type="button" onClick={suggest} disabled={!sample.trim() || busy === 'suggest'} title={!sample.trim() ? 'Paste or capture a sample first' : undefined} className="inline-flex items-center gap-1 rounded-md border border-cyan-500/50 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-500/10 disabled:opacity-50" data-testid="tel-map-suggest">
              {busy === 'suggest' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />} Suggest a mapping
            </button>
          </div>
          {capErr && (
            <div className="mb-2 flex flex-wrap items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-100" role="alert" data-testid="tel-map-capture-error">
              <span className="min-w-0 flex-1">{capErr}</span>
              <button type="button" onClick={capture} className="rounded-md border border-amber-500/50 px-2 py-0.5 hover:bg-amber-500/10" data-testid="tel-map-capture-retry">Retry</button>
              <button type="button" onClick={() => setCapErr(null)} className="rounded-md px-2 py-0.5 text-amber-200 hover:bg-amber-500/10">Dismiss</button>
            </div>
          )}
          <textarea value={sample} onChange={(e) => setSample(e.target.value)} rows={6} spellCheck={false} placeholder='{"asset": "pump-7", "ts": 1760000000000, "temperature_c": 61.5}' className={inputCls} data-testid="tel-map-sample" />
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Topic or subject it arrived on, for example plant/line-2/pump-7" className={`${inputCls} mt-2`} data-testid="tel-map-subject" />
          <p className="mt-1 text-xs text-slate-500">Paste one message as it arrives, or capture one. Nothing is stored from the preview.</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <Row label="Group" hint="Empty takes the first part of the topic">
            <input value={m.group} onChange={(e) => set({ group: e.target.value })} placeholder="plant-a" className={inputCls} data-testid="tel-map-group" />
          </Row>
          <Row label="Asset" hint="Empty takes the second part of the topic">
            <input value={m.node} onChange={(e) => set({ node: e.target.value })} placeholder="$.machine.id" className={inputCls} data-testid="tel-map-node" />
          </Row>
          <Row label="Part" hint="Optional, the rest of the topic if empty">
            <input value={m.device} onChange={(e) => set({ device: e.target.value })} placeholder="{subject.2}" className={inputCls} data-testid="tel-map-device" />
          </Row>
        </div>
        <p className="-mt-1 text-xs text-slate-500">
          Use <code className="text-slate-300">$.path</code> for a value in the message, <code className="text-slate-300">{'{subject.N}'}</code> for part N of the topic counting from 0, <code className="text-slate-300">{'{header.name}'}</code> for a header, or plain text for a fixed name.
        </p>
        {problems.templates && <p className="text-xs text-rose-300" role="alert" data-testid="tel-map-problem">{problems.templates}</p>}
        {problems.paths && <p className="text-xs text-rose-300" role="alert">{problems.paths}</p>}

        <Row label="Readings in a list" hint="If one message carries many readings, the path to the list, like $.readings. Each item is stored on its own.">
          <input value={m.records ?? ''} onChange={(e) => set({ records: e.target.value || undefined })} placeholder="$.readings" className={inputCls} data-testid="tel-map-records" />
        </Row>

        <div className="grid gap-3 sm:grid-cols-2">
          <Row label="Time of the reading" hint="Leave empty to use the time it arrived">
            <input value={m.timestamp.path} onChange={(e) => set({ timestamp: { ...m.timestamp, path: e.target.value } })} placeholder="$.ts" className={inputCls} data-testid="tel-map-ts" />
          </Row>
          <Row label="Time format">
            <select value={m.timestamp.format} onChange={(e) => set({ timestamp: { ...m.timestamp, format: e.target.value as TsFormat } })} className={inputCls.replace('font-mono ', '')} data-testid="tel-map-ts-format">
              {FORMATS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
            </select>
          </Row>
        </div>

        {suggestNote && <p className="rounded-md border border-cyan-500/30 bg-cyan-500/5 px-2 py-1.5 text-xs text-cyan-100" data-testid="tel-map-suggest-note">{suggestNote}</p>}

        <fieldset className="space-y-2 rounded-lg border border-slate-700/60 p-3" data-testid="tel-map-filter">
          <legend className="px-1 text-xs font-medium text-slate-300">Which messages to keep</legend>
          <p className="text-xs text-slate-500">Leave these empty to keep every message. Skipped messages are counted, not stored, and not sent to Problems.</p>
          <Row label="Must have" hint="Paths that must be there and not empty, one per line. Example: $.symbol">
            <textarea value={(m.filter?.require ?? []).join('\n')} onChange={(e) => setFilter({ require: splitList(e.target.value) })} rows={2} placeholder="$.symbol" className={inputCls} data-testid="tel-map-require" />
          </Row>
          <Row label="Only when" problem={matchParsed.problem ?? undefined} hint="path = value, or several values with commas. Example: $.type = tick">
            <textarea value={matchText} onChange={(e) => setFilter({ matchText: e.target.value })} rows={2} placeholder="$.type = tick" className={inputCls} data-testid="tel-map-match" />
          </Row>
          <Row label="Skip when" problem={excludeParsed.problem ?? undefined} hint="Example: $.type = subscribed, heartbeat">
            <textarea value={excludeText} onChange={(e) => setFilter({ excludeText: e.target.value })} rows={2} placeholder="$.type = subscribed, heartbeat" className={inputCls} data-testid="tel-map-exclude-rule" />
          </Row>
        </fieldset>

        <label className="flex items-start gap-2 text-sm text-slate-200">
          <input type="checkbox" checked={!!m.event} onChange={(e) => set({ event: e.target.checked ? { name: '' } : null })} className="mt-1 accent-cyan-500" data-testid="tel-map-event" />
          <span>Also store each message as one event<span className="block text-xs text-slate-500">For app streams like order.created, where the whole message matters, not only its numbers.</span></span>
        </label>
        {m.event && (
          <Row label="Event name" hint="A path like $.type, or plain text. Empty uses the topic.">
            <input value={m.event.name ?? ''} onChange={(e) => set({ event: { name: e.target.value } })} placeholder="$.type" className={inputCls} data-testid="tel-map-event-name" />
          </Row>
        )}

        {(
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <Row label="Only these signals" hint="Paths or names, one per line, a * at the end matches the rest. Empty keeps everything.">
                <textarea value={m.signals.include.join('\n')} onChange={(e) => set({ signals: { ...m.signals, include: splitList(e.target.value) } })} rows={2} placeholder="$.readings" className={inputCls} data-testid="tel-map-include" />
              </Row>
              <Row label="Leave out" hint="Paths or names, one per line, like an id already used for the asset">
                <textarea value={m.signals.exclude.join('\n')} onChange={(e) => set({ signals: { ...m.signals, exclude: splitList(e.target.value) } })} rows={2} placeholder="$.machine" className={inputCls} data-testid="tel-map-exclude" />
              </Row>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-200">
              <input type="checkbox" checked={m.signals.flatten} onChange={(e) => set({ signals: { ...m.signals, flatten: e.target.checked } })} className="accent-cyan-500" data-testid="tel-map-flatten" />
              Flatten nested values into names like engine/oil/temp
            </label>
            <Row label="Units">
              <ul className="space-y-1">
                {Object.entries(m.signals.units).map(([p, u]) => (
                  <li key={p} className="flex items-center gap-2 text-xs">
                    <code className="min-w-0 flex-1 truncate text-slate-300">{p}</code><span className="text-slate-200">{u}</span>
                    <button type="button" aria-label={`Remove the unit for ${p}`} onClick={() => { const units = { ...m.signals.units }; delete units[p]; set({ signals: { ...m.signals, units } }); }} className="p-1 text-slate-400 hover:text-rose-300"><Trash2 className="h-3.5 w-3.5" /></button>
                  </li>
                ))}
              </ul>
              <div className="mt-1 flex gap-2">
                <input value={unitPath} onChange={(e) => setUnitPath(e.target.value)} placeholder="$.temperature" className={inputCls} data-testid="tel-map-unit-path" />
                <input value={unitText} onChange={(e) => setUnitText(e.target.value)} placeholder="°C" className={`${inputCls} w-24`} data-testid="tel-map-unit" />
                <button type="button" onClick={() => { if (!unitPath.trim() || !unitText.trim()) return; set({ signals: { ...m.signals, units: { ...m.signals.units, [unitPath.trim()]: unitText.trim() } } }); setUnitPath(''); setUnitText(''); }} disabled={!unitPath.trim() || !unitText.trim()} title={!unitPath.trim() || !unitText.trim() ? 'Type a path and a unit first' : undefined} className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-700 px-2 text-xs text-slate-200 hover:bg-slate-800 disabled:opacity-50" data-testid="tel-map-unit-add">
                  <Plus className="h-3.5 w-3.5" /> Add
                </button>
              </div>
            </Row>
          </>
        )}
      </div>

      <div className="min-w-0">
        <div className="mb-1 flex items-center gap-2">
          <p className="flex-1 text-xs font-medium text-slate-300">What gets stored</p>
          {busy === 'preview' && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
        </div>
        <div className="min-h-[12rem] rounded-lg border border-slate-700 bg-slate-950/60 p-3 text-sm" data-testid="tel-map-preview">
          {err ? (
            <p className="text-rose-200" role="alert">{err}</p>
          ) : !sourceId ? (
            <p className="text-slate-400">Save the source first, then the preview shows what each message becomes.</p>
          ) : !sample.trim() ? (
            <p className="text-slate-400">Paste a sample or capture a live message to see the records it makes.</p>
          ) : !preview ? (
            <p className="text-slate-400">Working it out</p>
          ) : (
            <div className="space-y-2">
              {preview.skipped && (
                <p className="flex items-start gap-1.5 text-amber-200" data-testid="tel-map-skipped"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Skipped by filter{preview.skip_reason ? `: ${preview.skip_reason}` : ''}. Nothing from this message would be stored.</p>
              )}
              {preview.errors.map((e) => (
                <p key={e} className="flex items-start gap-1.5 text-rose-200" role="alert" data-testid="tel-map-error"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{e}</p>
              ))}
              {!preview.skipped && !preview.errors.length && !preview.records.length && <p className="text-amber-200">This sample makes no records. Check the asset path and the signals above.</p>}
              {preview.records.map((r, i) => (
                <div key={i} className="rounded-md border border-slate-800 p-2" data-testid="tel-map-record">
                  <p className="flex items-center gap-1.5 text-xs text-emerald-200"><CheckCircle2 className="h-3.5 w-3.5" /> {[r.group, r.node, r.device].filter(Boolean).join(' · ') || 'no asset'}{r.kind && r.kind !== 'data' ? ` · ${r.kind}` : ''}</p>
                  <table className="mt-1 w-full text-xs">
                    <tbody>
                      {r.metrics.slice(0, 30).map((x) => (
                        <tr key={x.name} className="border-t border-slate-800/60">
                          <td className="py-0.5 pr-2 font-mono text-slate-300">{x.name}</td>
                          <td className="py-0.5 text-right tabular-nums text-white">{typeof x.value === 'object' && x.value !== null ? JSON.stringify(x.value).slice(0, 60) : formatValue(x.value as never)}{x.unit ? ` ${x.unit}` : ''}</td>
                          <td className="hidden py-0.5 pl-2 text-right text-slate-500 sm:table-cell">{x.type}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {r.metrics.length > 30 && <p className="mt-1 text-xs text-slate-500">and {r.metrics.length - 30} more signals</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
