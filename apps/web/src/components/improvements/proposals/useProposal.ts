'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { asProposal, isWorking, proposalsApi, type Proposal } from '@/lib/improvement-proposals';

// keeps one proposal fresh: every 2 s while it is being proved, every 30 s while a release is watched
export function useProposal(initial: unknown) {
  const [p, setP] = useState<Proposal>(() => asProposal(initial));
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  useEffect(() => {
    setP(asProposal(initial));
  }, [initial]);

  const refresh = useCallback(async () => {
    if (!p.id) return;
    const r = await proposalsApi.get(p.id);
    if (!alive.current) return;
    if (r.error || !r.data) {
      setError(r.error || 'The proposal could not be loaded.');
      return;
    }
    setError(null);
    setP(asProposal(r.data));
  }, [p.id]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    const every = isWorking(p) ? 2000 : p.state === 'released' ? 30000 : 0;
    if (!every || !p.id) return;
    const t = setInterval(refresh, every);
    return () => clearInterval(t);
  }, [p, refresh]);

  return { p, setP: (v: unknown) => setP(asProposal(v)), refresh, error };
}

export function focusedProposalId(): string | null {
  try {
    return new URLSearchParams(window.location.search).get('proposal');
  } catch {
    return null;
  }
}
