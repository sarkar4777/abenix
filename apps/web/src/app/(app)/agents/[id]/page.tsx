// /agents/[id] redirects to the canonical detail page (/info).
// /agents/new is handled by a separate route file (../new/page.tsx)
// because Next.js's static optimization elides simple if-checks here.
import { redirect } from 'next/navigation';

export default async function AgentIndex(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  redirect(`/agents/${params.id}/info`);
}
