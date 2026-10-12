'use client';

import { CircleAlert, X } from 'lucide-react';

// a link named an item this list does not have
export default function DeepLinkMissing({ noun, id, onDismiss, testId = 'deeplink-missing' }: {
  noun: string;
  id: string;
  onDismiss: () => void;
  testId?: string;
}) {
  return (
    <div role="alert" data-testid={testId}
      className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
      <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" aria-hidden />
      <p className="min-w-0 flex-1 break-words">
        Could not open the {noun} <code className="text-amber-200">{id}</code>. It may have been deleted, or it is not shared with you.
      </p>
      <button type="button" onClick={onDismiss} aria-label="Dismiss" data-testid={`${testId}-dismiss`}
        className="rounded p-0.5 text-amber-200 hover:bg-amber-500/20">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
