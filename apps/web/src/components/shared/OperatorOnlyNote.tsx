'use client';

import ViewOnlyBanner from '@/components/shared/ViewOnlyBanner';

export default function OperatorOnlyNote({ what, rule }: { what: string; rule?: string }) {
  return (
    <ViewOnlyBanner testId="operator-only-note">
      {what} applies to every workspace on this deployment, so only a platform operator can change it. {rule}
    </ViewOnlyBanner>
  );
}
