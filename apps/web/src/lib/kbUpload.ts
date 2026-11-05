import { API_URL } from '@/lib/api-client';

// below this the plain multipart route is simplest, above it the file skips the API's disk
export const LARGE_FILE_BYTES = 32 * 1024 * 1024;
const PART_CONCURRENCY = 4;

export const ACCEPTED_EXTENSIONS = '.pdf,.docx,.pptx,.xlsx,.html,.htm,.msg,.txt,.csv,.tsv,.md,.json,.log';
export const ACCEPTED_LABEL = 'PDF, DOCX, PPTX, XLSX, HTML, MSG, TXT, CSV, MD, JSON';

export interface UploadResult {
  document?: Record<string, unknown>;
  error?: string;
}

type Headers = Record<string, string>;

const reason = async (res: Response): Promise<string> => {
  const json = await res.json().catch(() => ({}));
  const message = typeof json.error === 'string' ? json.error : json.error?.message;
  return message || `upload failed (${res.status})`;
};

const absolute = (path: string) => (path.startsWith('http') ? path : `${API_URL}${path}`);

async function inParallel<T>(items: T[], limit: number, work: (item: T) => Promise<void>) {
  const queue = [...items];
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    for (let item = queue.shift(); item !== undefined; item = queue.shift()) {
      await work(item);
    }
  });
  await Promise.all(workers);
}

async function sendS3Parts(file: File, upload: { part_size: number; parts: { part_number: number; url: string }[] }) {
  const done: { part_number: number; etag: string }[] = [];
  await inParallel(upload.parts, PART_CONCURRENCY, async (part) => {
    const start = (part.part_number - 1) * upload.part_size;
    const res = await fetch(part.url, { method: 'PUT', body: file.slice(start, start + upload.part_size) });
    const etag = res.headers.get('ETag');
    if (!res.ok || !etag) {
      throw new Error(res.ok ? 'the bucket CORS rule must expose the ETag header' : `part ${part.part_number} was refused (${res.status})`);
    }
    done.push({ part_number: part.part_number, etag });
  });
  return done;
}

async function sendAzureBlocks(file: File, upload: { part_size: number; url: string }) {
  const count = Math.max(1, Math.ceil(file.size / upload.part_size));
  const blocks = Array.from({ length: count }, (_, i) => ({ index: i, block_id: btoa(String(i).padStart(10, '0')) }));
  await inParallel(blocks, PART_CONCURRENCY, async ({ index, block_id }) => {
    const start = index * upload.part_size;
    const res = await fetch(`${upload.url}&comp=block&blockid=${encodeURIComponent(block_id)}`, {
      method: 'PUT',
      headers: { 'x-ms-blob-type': 'BlockBlob' },
      body: file.slice(start, start + upload.part_size),
    });
    if (!res.ok) throw new Error(`block ${index} was refused (${res.status})`);
  });
  return blocks.map(({ block_id }) => ({ block_id }));
}

export async function uploadLargeFile(kbId: string, file: File, headers: Headers): Promise<UploadResult> {
  const jsonHeaders = { ...headers, 'Content-Type': 'application/json' };
  const planned = await fetch(`${API_URL}/api/knowledge-bases/${kbId}/uploads`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({
      files: [{ filename: file.name, size: file.size, content_type: file.type || null }],
    }),
  });
  if (!planned.ok) return { error: await reason(planned) };
  const plan = (await planned.json()).data[0];
  if (plan.mode === 'rejected') return { error: plan.error };
  if (plan.document) return { document: plan.document };

  if (plan.mode === 'stream') {
    const res = await fetch(absolute(plan.url), {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    if (!res.ok) return { error: await reason(res) };
    return { document: (await res.json()).data };
  }

  try {
    const parts =
      plan.upload.kind === 'azure_blocks'
        ? await sendAzureBlocks(file, plan.upload)
        : await sendS3Parts(file, plan.upload);
    const res = await fetch(absolute(plan.complete_url), {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ parts }),
    });
    if (!res.ok) return { error: await reason(res) };
    return { document: (await res.json()).data };
  } catch (err) {
    await fetch(absolute(plan.abort_url), { method: 'DELETE', headers }).catch(() => undefined);
    return { error: err instanceof Error ? err.message : 'upload failed' };
  }
}
