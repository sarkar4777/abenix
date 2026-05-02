// Convenience URL: /agents/new redirects to the agent builder.
// Without this page, /agents/new would fall through to /agents/[id] with
// id="new", which has no real agent to show and bounces to /agents/new/info.
import { redirect } from 'next/navigation';

export default function NewAgentRedirect() {
  redirect('/builder');
}
