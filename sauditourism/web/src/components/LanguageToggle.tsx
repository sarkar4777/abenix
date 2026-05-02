'use client';

/**
 * Bare-bones EN | عر language toggle.
 *
 * For Phase A7 we only flip <html dir> and persist a localStorage key.
 * Full i18n strings (next-intl / dictionaries) are deferred to Phase B.
 *
 * TODO(phase-b): swap localStorage flag for next-intl provider + JSON
 * dictionaries covering nav labels, dashboard KPI labels, report-type
 * names, and simulation preset titles.
 */

import { useEffect, useState } from 'react';

type Lang = 'en' | 'ar';

function applyLang(lang: Lang) {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute('lang', lang);
  document.documentElement.setAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
}

export default function LanguageToggle() {
  const [lang, setLang] = useState<Lang>('en');

  useEffect(() => {
    const stored = (localStorage.getItem('st_lang') as Lang) || 'en';
    setLang(stored);
    applyLang(stored);
  }, []);

  function toggle() {
    const next: Lang = lang === 'en' ? 'ar' : 'en';
    setLang(next);
    localStorage.setItem('st_lang', next);
    applyLang(next);
  }

  return (
    <button
      onClick={toggle}
      title="Toggle language (EN / العربية)"
      className="text-[11px] px-2 py-1 rounded-md border border-green-800/40 bg-green-900/30 text-green-200/70 hover:text-white hover:border-green-600/60 transition-colors"
    >
      {lang === 'en' ? 'EN | عر' : 'عر | EN'}
    </button>
  );
}
