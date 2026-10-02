'use client';

export type Ownership = 'mine' | 'shared' | 'platform';

interface Props {
  ownership?: Ownership | string | null;
  ownerName?: string | null;
  className?: string;
}

const STYLES: Record<Ownership, string> = {
  mine: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  shared: 'text-cyan-300 bg-cyan-500/10 border-cyan-500/30',
  platform: 'text-slate-300 bg-slate-700/40 border-slate-600/50',
};

export default function OwnerBadge({ ownership, ownerName, className = '' }: Props) {
  if (ownership !== 'mine' && ownership !== 'shared' && ownership !== 'platform') return null;
  const label =
    ownership === 'mine' ? 'Yours' : ownership === 'platform' ? 'Platform' : `Shared by ${ownerName || 'a teammate'}`;
  return (
    <span
      data-testid="owner-badge"
      data-ownership={ownership}
      title={label}
      className={`inline-flex items-center max-w-[160px] truncate px-1.5 py-0.5 rounded border text-[9px] font-medium ${STYLES[ownership]} ${className}`}
    >
      {label}
    </span>
  );
}
