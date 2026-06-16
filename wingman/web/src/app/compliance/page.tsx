'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function CompliancePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/mispricing#compliance');
  }, [router]);
  return (
    <div className="min-h-screen flex items-center justify-center text-slate-300">
      <div className="text-center">
        <p className="text-lg">Compliance Lens lives inside the Mispricing trade card.</p>
        <p className="text-sm text-slate-500 mt-2">Redirecting...</p>
      </div>
    </div>
  );
}
