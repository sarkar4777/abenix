import { redirect } from 'next/navigation';

// Convenience top-level URL — the actual webhooks UI lives under
// /settings/webhooks. We redirect server-side so guessed URLs and
// older docs links resolve cleanly instead of 404'ing.
export default function WebhooksRedirect() {
  redirect('/settings/webhooks');
}
