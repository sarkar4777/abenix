// Read-back helpers for the dev catchers and a TOTP generator for two-step sign-in.
import crypto from 'node:crypto';
import { expect, type APIRequestContext } from '@playwright/test';

export const MAILPIT = process.env.MAILPIT || 'http://localhost:8025';
export const CATCHER = process.env.CATCHER || 'http://localhost:8091';

export interface Mail {
  ID: string;
  Subject: string;
  To: { Address: string }[];
  Created: string;
}

export async function mailsTo(req: APIRequestContext, to: string): Promise<Mail[]> {
  const r = await req.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}`);
  if (!r.ok()) return [];
  return ((await r.json()).messages || []) as Mail[];
}

// waits for a mail to `to` whose subject matches, newest first
export async function waitForMail(
  req: APIRequestContext,
  to: string,
  subject: RegExp,
  opts: { timeout?: number; after?: string[] } = {},
): Promise<{ id: string; subject: string; text: string; html: string }> {
  const seen = new Set(opts.after || []);
  let hit: Mail | undefined;
  await expect
    .poll(
      async () => {
        hit = (await mailsTo(req, to)).find((m) => subject.test(m.Subject) && !seen.has(m.ID));
        return !!hit;
      },
      { timeout: opts.timeout ?? 60_000, message: `mail to ${to} matching ${subject}` },
    )
    .toBeTruthy();
  const full = await (await req.get(`${MAILPIT}/api/v1/message/${hit!.ID}`)).json();
  return { id: hit!.ID, subject: full.Subject, text: full.Text || '', html: full.HTML || '' };
}

export function firstLink(text: string, contains: string): string {
  const m = text.match(new RegExp(`https?://\\S*${contains.replace(/[.?]/g, '\\$&')}\\S*`));
  if (!m) throw new Error(`no link containing ${contains} in:\n${text}`);
  return m[0].replace(/[).,>]+$/, '');
}

export interface Caught {
  path: string;
  json: any;
  body: string;
  received_at: string;
}

export async function caught(req: APIRequestContext, path: string): Promise<Caught[]> {
  const r = await req.get(`${CATCHER}/api/requests?path=${encodeURIComponent(path)}`);
  if (!r.ok()) return [];
  return ((await r.json()).items || []) as Caught[];
}

export async function waitForPost(
  req: APIRequestContext,
  path: string,
  match: (c: Caught) => boolean,
  timeout = 60_000,
): Promise<Caught> {
  let hit: Caught | undefined;
  await expect
    .poll(
      async () => {
        hit = (await caught(req, path)).find(match);
        return !!hit;
      },
      { timeout, message: `post to ${path}` },
    )
    .toBeTruthy();
  return hit!;
}

function base32(s: string): Buffer {
  const alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of s.replace(/=+$/, '').toUpperCase()) {
    const v = alpha.indexOf(ch);
    if (v < 0) continue;
    bits += v.toString(2).padStart(5, '0');
  }
  const out: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) out.push(parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(out);
}

export function totpStep(now = Date.now()): number {
  return Math.floor(now / 1000 / 30);
}

export function totp(secret: string, step = totpStep()): string {
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(step));
  const h = crypto.createHmac('sha1', base32(secret)).update(buf).digest();
  const off = h[h.length - 1] & 0x0f;
  const n = (h.readUInt32BE(off) & 0x7fffffff) % 1_000_000;
  return String(n).padStart(6, '0');
}

// a code from a step later than `used`, waiting for the clock when needed
export async function freshTotp(secret: string, used: number | null): Promise<{ code: string; step: number }> {
  while (used !== null && totpStep() <= used) {
    await new Promise((r) => setTimeout(r, 1000));
  }
  const step = totpStep();
  return { code: totp(secret, step), step };
}
