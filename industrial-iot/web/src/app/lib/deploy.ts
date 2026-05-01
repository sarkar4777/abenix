import { apiFetch } from '@/lib/api-client';

export interface AssetSpec {
  slug: string;
  display_name: string;
  description: string;
  language: 'go' | 'python';
  download_path: string; // relative to the web app root
}

export const PUMP_DSP: AssetSpec = {
  slug: 'pump-dsp-correction',
  display_name: 'Pump Vibration DSP (Go)',
  description:
    'Vibration-signal DSP for rotating machinery — FFT, RMS, crest factor, kurtosis, per-fault scores.',
  language: 'go',
  download_path: '/industrial-iot/pump-dsp-correction.zip',
};

export const RUL_ESTIMATOR: AssetSpec = {
  slug: 'rul-estimator',
  display_name: 'Remaining-Useful-Life Estimator (Python)',
  description:
    'Exponential degradation fit on health-index history → RUL in hours.',
  language: 'python',
  download_path: '/industrial-iot/rul-estimator.zip',
};

export const COLDCHAIN_CORRECTOR: AssetSpec = {
  slug: 'cold-chain-corrector',
  display_name: 'Cold-Chain Telemetry Corrector (Go)',
  description:
    'Kalman-smoothed reefer temperature + excursion & door-event detection.',
  language: 'go',
  download_path: '/industrial-iot/cold-chain-corrector.zip',
};

export interface CodeAssetRow {
  id: string;
  name: string;
  status: string;
  suggested_image?: string;
  suggested_build_command?: string;
  suggested_run_command?: string;
  input_schema?: Record<string, unknown> | null;
  output_schema?: Record<string, unknown> | null;
  error?: string | null;
}

/** Look up an asset the caller owns by its uploaded name. Optionally
 *  filter out assets that predate analyzer fixes so we don't rehydrate
 *  a broken deploy into the "Deployed" pill on mount. */
export async function findAssetByName(
  name: string,
  opts: { spec?: AssetSpec; skipStale?: boolean } = {},
): Promise<CodeAssetRow | null> {
  const res = await apiFetch<CodeAssetRow[]>('/api/code-assets?scope=all');
  if (!res.data) return null;
  const matches = res.data.filter(
    (a) => a.name === name || a.name.startsWith(name + '-'),
  );
  // Prefer newest → oldest so a fresh re-upload wins over a stale row.
  matches.sort((a, b) => b.id.localeCompare(a.id));
  for (const hit of matches) {
    if (opts.skipStale && opts.spec && isStaleAsset(opts.spec, hit)) continue;
    return hit;
  }
  return null;
}

async function fetchZipBlob(path: string): Promise<Blob> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`asset zip not found at ${path}`);
  return await r.blob();
}

async function pollUntilReady(
  id: string,
  { timeoutMs = 180_000, pollMs = 3_000 } = {},
): Promise<CodeAssetRow> {
  const deadline = Date.now() + timeoutMs;
  let last: CodeAssetRow | null = null;
  while (Date.now() < deadline) {
    const r = await apiFetch<CodeAssetRow>(`/api/code-assets/${id}`);
    if (r.data) {
      last = r.data;
      if (r.data.status === 'failed') {
        throw new Error(`analysis failed: ${r.data.error ?? 'unknown error'}`);
      }
      // We consider it DEPLOYED once status=ready. output_schema
      // populates asynchronously via the smoke-test probe, which runs
      // the code in a k8s Job — we surface that separately so the UI
      // can show "probe pending" vs. "probe complete".
      if (r.data.status === 'ready') return r.data;
    }
    await new Promise((res) => setTimeout(res, pollMs));
  }
  throw new Error(
    `asset ${id} did not reach ready status within ${timeoutMs / 1000}s` +
      (last ? ` (last=${last.status})` : ''),
  );
}

function isStaleAsset(spec: AssetSpec, a: CodeAssetRow): boolean {
  const cmd = a.suggested_build_command || '';
  if (spec.language === 'go' && cmd.includes(' -o /tmp/bin') && !cmd.includes('./cmd')) {
    return true;
  }
  return false;
}

export async function uploadAndDeploy(
  spec: AssetSpec,
  opts: { reuseExisting?: boolean } = { reuseExisting: true },
): Promise<CodeAssetRow> {
  if (opts.reuseExisting) {
    const existing = await findAssetByName(spec.slug);
    if (existing && existing.status === 'ready' && !isStaleAsset(spec, existing)) {
      return existing;
    }
  }

  const zipBlob = await fetchZipBlob(spec.download_path);
  const fd = new FormData();
  fd.append(
    'file',
    new File([zipBlob], `${spec.slug}.zip`, { type: 'application/zip' }),
  );
  fd.append(
    'metadata',
    JSON.stringify({
      name: spec.slug,
      description: spec.description,
    }),
  );
  const up = await apiFetch<CodeAssetRow>('/api/code-assets', {
    method: 'POST',
    body: fd,
    headers: {},
  });
  if (!up.data) throw new Error(up.error ?? 'upload failed');
  return await pollUntilReady(up.data.id);
}

/**
 * Convenience: poll until the smoke-test probe populates
 * output_schema. Non-fatal if it never does — the asset still works.
 */
export async function waitForSchemaProbe(
  id: string,
  { timeoutMs = 120_000, pollMs = 3_000 } = {},
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const r = await apiFetch<CodeAssetRow>(`/api/code-assets/${id}`);
    if (r.data?.output_schema) return true;
    await new Promise((res) => setTimeout(res, pollMs));
  }
  return false;
}
