import { NextRequest } from 'next/server';

import { forwardHeaders } from '../../_forward';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const INTERNAL = process.env.CONTRACTIQ_API_INTERNAL_URL || 'http://localhost:8001';

export async function GET(req: NextRequest) {
  const url = new URL(`${INTERNAL}/api/contractiq/ml-models/invocations`);
  for (const [k, v] of req.nextUrl.searchParams.entries()) url.searchParams.append(k, v);
  try {
    const r = await fetch(url.toString(), { cache: 'no-store', headers: forwardHeaders(req) });
    if (!r.ok) return Response.json({ data: [] }, { status: r.status });
    return Response.json(await r.json());
  } catch {
    return Response.json({ data: [] });
  }
}
