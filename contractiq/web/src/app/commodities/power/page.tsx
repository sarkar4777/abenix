import { redirect } from 'next/navigation';

// Legacy hardcoded hub is retired. The selector-driven /commodities/forward
// page is canonical for every commodity now — same agent runtime, real
// numbers, one mental model.
export default function PowerHubRedirect() {
  redirect('/commodities/forward?commodity=power');
}
