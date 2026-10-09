'use client';

import { Eye, Sprout } from 'lucide-react';
import NextSteps, { type NextStep } from '@/components/shared/NextSteps';
import type { Decided } from './ImprovementApprovalCard';

// Shown by the list that held an approved fix, the card itself is gone by then.
export default function ReleasedNext({ decided, onDismiss }: { decided: Decided | null; onDismiss: () => void }) {
  if (!decided || decided.decision !== 'approve') return null;
  const steps: NextStep[] = [];
  if (decided.link) {
    steps.push({
      id: 'watch',
      label: 'Watch the release',
      hint: 'It is compared with the old version for 7 days or 200 runs and rolled back on its own if it does worse.',
      icon: Eye,
      href: decided.link,
    });
  }
  steps.push({
    id: 'improvements',
    label: 'See what else agents learned',
    hint: 'Other groups of lessons and fixes waiting to be proposed.',
    icon: Sprout,
    href: '/improvements',
  });
  return (
    <NextSteps
      title={decided.agentName ? `Approved. The fix to ${decided.agentName} is released.` : 'Approved. The fix is released.'}
      steps={steps}
      onDismiss={onDismiss}
      testId="release-next"
      className="mb-3"
    />
  );
}
