import { NextRequest } from 'next/server';

import { forwardHeaders } from '../../_forward';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const INTERNAL = process.env.CONTRACTIQ_API_INTERNAL_URL || 'http://localhost:8001';

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const replay = req.nextUrl.searchParams.get('replay');
  const speed = req.nextUrl.searchParams.get('speed');
  const path = replay
    ? `/api/contractiq/narration/${id}/replay${speed ? `?speed=${speed}` : ''}`
    : `/api/contractiq/narration/${id}`;
  try {
    const upstream = await fetch(`${INTERNAL}${path}`, {
      headers: { Accept: 'text/event-stream', ...forwardHeaders(req) },
      cache: 'no-store',
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-store, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch {
    return new Response('', { status: 502, headers: { 'Content-Type': 'text/event-stream' } });
  }
}
