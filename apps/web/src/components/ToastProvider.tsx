'use client';

import { useEffect } from 'react';
import { onApiToast } from '@/lib/api-client';
import { useToastStore } from '@/stores/toastStore';
import { ToastContainer } from '@/components/ui/Toast';

// API client warnings join the same stack as toastSuccess/toastError calls.
export function ToastProvider({ children }: { children: React.ReactNode }) {
  useEffect(
    () =>
      onApiToast((message, type) => {
        useToastStore.getState().addToast({ type, title: message, duration: 6000 });
      }),
    [],
  );

  return (
    <>
      {children}
      <ToastContainer />
    </>
  );
}
