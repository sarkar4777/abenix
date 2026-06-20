import { redirect } from 'next/navigation';

// LNG now ships through the agent-driven forward page. The old hardcoded
// hub view shipped fabricated spot prices and curve data — that page is
// retired so we keep one source of truth (the contractiq_lng_fairvalue
// agent + JKM live anchor) for every LNG number the analyst sees.
export default function LngHubRedirect() {
  redirect('/commodities/forward?commodity=lng');
}
