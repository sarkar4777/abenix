'use client';


import { useEffect, useState } from 'react';
import { ShieldAlert, Terminal, Clock, ChevronDown, AlertCircle, Info } from 'lucide-react';
import { apiFetch, API_URL } from '@/lib/api-client';

interface Props {
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

// Fallback when the platform-settings endpoint isn't reachable — same
// baked-in allow-list the Helm chart ships.
const FALLBACK_IMAGES = [
  'alpine:3.20',
  'busybox:1.36',
  'python:3.12-slim',
  'node:20-alpine',
  'golang:1.22-alpine',
  'rust:1.75-slim',
  'ruby:3.3-alpine',
  'eclipse-temurin:21-jdk',
];

const COMMAND_EXAMPLES: Record<string, string> = {
  'python:3.12-slim': 'python -c "import json, sys; d=json.loads(sys.stdin.read() or \\"{}\\"); print(json.dumps({\\"ok\\": True, \\"input\\": d}))"',
  'node:20-alpine': 'node -e "let d=\'\';process.stdin.on(\'data\',c=>d+=c).on(\'end\',()=>{console.log(JSON.stringify({ok:true,input:JSON.parse(d||\'{}\')}))})"',
  'golang:1.22-alpine': 'echo hello from go',
  'eclipse-temurin:21-jdk': 'java -version 2>&1',
  'alpine:3.20': 'cat /etc/os-release',
  'busybox:1.36': 'echo hello',
  'rust:1.75-slim': 'rustc --version',
  'ruby:3.3-alpine': 'ruby -e "puts({ok: true}.to_json)"',
};

export default function SandboxedJobConfig({ values, onChange }: Props) {
  const [images, setImages] = useState<string[]>(FALLBACK_IMAGES);
  useEffect(() => {
    // Best-effort: try to fetch the real allow-list from the cluster so we don't
    // drift from the operator's SANDBOXED_JOB_ALLOWED_IMAGES.
    apiFetch<{ images: string[] }>(`${API_URL}/api/admin/sandbox/images`).then((r) => {
      if (r?.data?.images?.length) setImages(r.data.images);
    }).catch(() => {/* silent — fallback stays */});
  }, []);

  const image = (values.image as string) || '';
  const command = (values.command as string) || '';

  return (
    <div className="space-y-4" data-testid="sandboxed-job-config">
      {/* ───── What this tool does ───── */}
      <div className="rounded-lg border border-slate-700/40 bg-slate-900/30 p-3 text-[11px] text-slate-300 leading-relaxed">
        <p className="flex items-center gap-1.5 text-cyan-400 font-semibold mb-1">
          <Info className="w-3 h-3" /> What this tool does
        </p>
        Runs a shell command in a fresh k8s Pod using one of the allow-listed
        images. Stdin is the JSON payload from the caller; stdout is what
        comes back as the tool's result. The pod is torn down when the
        command exits. For long-running code, upload a zip to Code Runner and
        use the <code>code_asset</code> tool instead.
      </div>

      {/* ───── Image picker ───── */}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1.5">
          <ShieldAlert className="w-3 h-3" /> Base image
        </label>
        <div className="relative">
          <select
            value={image}
            onChange={(e) => onChange({ ...values, image: e.target.value })}
            className="w-full appearance-none bg-slate-900/60 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-cyan-500"
            data-testid="sandboxed-image"
          >
            <option value="">— choose an image —</option>
            {images.map((img) => (
              <option key={img} value={img}>{img}</option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
        <p className="text-[10px] text-slate-500 mt-1">
          Only allow-listed images run. Ask an admin if you need a new base image.
        </p>
      </div>

      {/* ───── Command ───── */}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 flex items-center gap-1.5">
          <Terminal className="w-3 h-3" /> Command (runs inside the pod)
        </label>
        <textarea
          value={command}
          onChange={(e) => onChange({ ...values, command: e.target.value })}
          placeholder={image ? COMMAND_EXAMPLES[image] || 'e.g. echo hello' : 'e.g. python -c "print(42)"'}
          rows={4}
          className="w-full bg-slate-900/60 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 font-mono focus:outline-none focus:border-cyan-500"
          data-testid="sandboxed-command"
        />
        {image && COMMAND_EXAMPLES[image] && (
          <button
            onClick={() => onChange({ ...values, command: COMMAND_EXAMPLES[image] })}
            className="text-[10px] text-cyan-400 hover:text-cyan-300 mt-1 underline"
          >
            Use example for {image}
          </button>
        )}
      </div>

      {/* ───── Timeout ───── */}
      <div>
        <label className="text-[10px] uppercase tracking-wider text-slate-500 mb-1 flex items-center gap-1.5">
          <Clock className="w-3 h-3" /> Timeout (seconds)
        </label>
        <input
          type="number"
          min={5}
          max={1800}
          value={(values.timeout_seconds as number) ?? 60}
          onChange={(e) => onChange({ ...values, timeout_seconds: Number(e.target.value) })}
          className="w-32 bg-slate-900/60 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white"
          data-testid="sandboxed-timeout"
        />
        <p className="text-[10px] text-slate-500 mt-1">
          Kill-after for the pod. Default 60s, max 1800s.
        </p>
      </div>

      {/* ───── Network off callout ───── */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-[11px] text-amber-200 leading-relaxed">
        <p className="flex items-center gap-1.5 font-semibold mb-1">
          <AlertCircle className="w-3 h-3" /> Network is off by default
        </p>
        Pods can't reach the public internet unless an admin has set{' '}
        <code>SANDBOXED_JOB_ALLOW_NETWORK=true</code>. If you need pip / npm /
        go-get to run inside the command, upload a pre-built zip to Code Runner
        and use <code>code_asset</code> instead.
      </div>
    </div>
  );
}
