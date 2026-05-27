import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const INTERNAL = process.env.CONTRACTIQ_API_INTERNAL_URL || 'http://localhost:8001';

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  try {
    const upstream = await fetch(`${INTERNAL}/api/contractiq/executions/${id}/watch`, {
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
  } catch {
    return new Response('', { status: 502, headers: { 'Content-Type': 'text/event-stream' } });
  }
}
