'use client';

// masked runs read as a quiet placeholder, not a glaring white bar, the characters stay for copy and search
export default function MaskedText({ text, mask = '█' }: { text: string; mask?: string }) {
  const unit = mask.trim()[0] || '█';
  const re = new RegExp(`(${unit.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}+)`, 'g');
  const parts = text.split(re);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span
            key={i}
            title="Hidden by your moderation policy"
            aria-label="hidden text"
            className="mx-0.5 rounded bg-slate-600/50 px-1 text-[0.8em] tracking-[-0.2em] text-slate-500 align-[0.05em]"
          >
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}
