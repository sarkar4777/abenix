// /agents/[id] redirects to the canonical detail page (/info).
// /agents/new is handled by a separate route file (../new/page.tsx)
// because Next.js's static optimization elides simple if-checks here.
import { redirect } from 'next/navigation';

export default function AgentIndex({ params }: { params: { id: string } }) {
  redirect(`/agents/${params.id}/info`);
}
