import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const INTERNAL = process.env.WINGMAN_API_INTERNAL_URL || 'http://localhost:8006';

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const replay = req.nextUrl.searchParams.get('replay');
  const speed = req.nextUrl.searchParams.get('speed');
  const path = replay
    ? `/api/wingman/desk/narration/${id}/replay${speed ? `?speed=${speed}` : ''}`
    : `/api/wingman/desk/narration/${id}`;
  const upstream = await fetch(`${INTERNAL}${path}`, {
    headers: { Accept: 'text/event-stream' },
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
}
