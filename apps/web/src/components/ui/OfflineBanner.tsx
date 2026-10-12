'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { WifiOff, Wifi, RefreshCw } from 'lucide-react';
import { getApiConnection, onApiConnection, type ApiConnection } from '@/lib/api-client';

export default function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(true);
  const [showRestored, setShowRestored] = useState(false);
  const [wasOffline, setWasOffline] = useState(false);
  const [api, setApi] = useState<ApiConnection>('ok');

  useEffect(() => {
    setApi(getApiConnection());
    return onApiConnection(setApi);
  }, []);

  const handleOnline = useCallback(() => {
    setIsOnline(true);
    if (wasOffline) {
      setShowRestored(true);
      const timer = setTimeout(() => {
        setShowRestored(false);
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [wasOffline]);

  const handleOffline = useCallback(() => {
    setIsOnline(false);
    setWasOffline(true);
    setShowRestored(false);
  }, []);

  useEffect(() => {
    setIsOnline(navigator.onLine);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [handleOnline, handleOffline]);

  const busy = isOnline && api === 'reconnecting';
  const showBanner = !isOnline || showRestored || busy;

  return (
    <AnimatePresence>
      {showBanner && (
        <motion.div
          initial={{ y: '-100%' }}
          animate={{ y: 0 }}
          exit={{ y: '-100%' }}
          transition={{ type: 'spring', stiffness: 300, damping: 30 }}
          className="fixed top-0 left-0 right-0 z-[80]"
        >
          {busy ? (
            <div role="status" className="bg-amber-500/90 backdrop-blur-sm text-slate-950">
              <div className="flex items-center justify-center gap-2 py-2 px-4">
                <RefreshCw className="w-4 h-4 flex-shrink-0 animate-spin" />
                <span className="text-sm font-medium">
                  Reconnecting… The server is busy, your work is safe and we keep retrying.
                </span>
              </div>
            </div>
          ) : !isOnline ? (
            <div className="bg-red-500/90 backdrop-blur-sm text-white">
              <div className="flex items-center justify-center gap-2 py-2 px-4">
                <WifiOff className="w-4 h-4 flex-shrink-0" />
                <span className="text-sm font-medium">
                  Connection lost. Reconnecting...
                </span>
                <RefreshCw className="w-4 h-4 flex-shrink-0 animate-spin" />
              </div>
            </div>
          ) : (
            <div className="bg-emerald-500/90 backdrop-blur-sm text-white">
              <div className="flex items-center justify-center gap-2 py-2 px-4">
                <Wifi className="w-4 h-4 flex-shrink-0" />
                <span className="text-sm font-medium">
                  Connection restored
                </span>
              </div>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
