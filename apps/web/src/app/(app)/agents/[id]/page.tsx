// /agents/[id] has historically been linked to from various places (grouped
// view, notifications, shared links) even though no page lived there — the
// canonical detail views are /info, /chat, /memories. This stub redirects
// to /info so those stale links stop 404-ing.
import { redirect } from 'next/navigation';

export default function AgentIndex({ params }: { params: { id: string } }) {
  redirect(`/agents/${params.id}/info`);
}
