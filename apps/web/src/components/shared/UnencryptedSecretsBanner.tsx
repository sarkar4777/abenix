'use client';

import { Unlock } from 'lucide-react';
import { useApi } from '@/hooks/useApi';
import { docHref } from '@/components/layout/PageHeader';

interface SecretStorage {
  encrypted_at_rest: boolean;
  message: string | null;
  doc_slug: string;
}

export default function UnencryptedSecretsBanner() {
  const { data } = useApi<SecretStorage>('/api/admin/secret-storage');
  if (!data || data.encrypted_at_rest) return null;
  return (
    <div
      role="alert"
      data-testid="secrets-unencrypted-banner"
      className="mb-6 flex items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200"
    >
      <Unlock className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
      <div>
        <p className="font-medium">Secrets are stored unencrypted. Set ABENIX_DATA_KEY_KEK_BASE64 to encrypt them.</p>
        <p className="mt-1 text-amber-200/80">
          Keys and passwords saved here go to the database as entered until the cluster key is set and the API is
          restarted.{' '}
          <a href={docHref(data.doc_slug)} target="_blank" rel="noreferrer" className="text-cyan-300 hover:underline">
            How to set the key
          </a>
        </p>
      </div>
    </div>
  );
}
