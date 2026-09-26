import { NextRequest } from 'next/server';

import { forwardHeaders } from '../../_forward';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const INTERNAL = process.env.CONTRACTIQ_API_INTERNAL_URL || 'http://localhost:8001';

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const r = await fetch(`${INTERNAL}/api/contractiq/executions/${id}`, {
      cache: 'no-store',
      headers: forwardHeaders(req),
    });
    if (!r.ok) return Response.json({ data: null }, { status: r.status });
    return Response.json(await r.json());
  } catch {
    return Response.json({ data: null });
  }
}
