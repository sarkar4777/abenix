'use client';

import { useEffect, useRef, useState, type InputHTMLAttributes } from 'react';
import { numberDraft } from '@/lib/decisionValues';

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

export type Parsed<T> = { hold: true } | { hold?: false; value: T };

type Props<T> = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> & {
  value: T;
  format: (v: T) => string;
  parse: (text: string) => Parsed<T>;
  onValue: (v: T) => void;
  onCommit?: (v: T) => void;
};

// keeps the text the person typed and only hands on what it means, so "0." stays "0." while they type 0.5
export function DraftInput<T>({ value, format, parse, onValue, onCommit, onBlur, onKeyDown, ...rest }: Props<T>) {
  const [text, setText] = useState(() => format(value));
  const sent = useRef<{ v: T } | null>(null);

  useEffect(() => {
    if (sent.current && same(sent.current.v, value)) return;
    sent.current = null;
    setText(format(value));
  }, [value]);

  function commit() {
    const p = parse(text);
    const v = p.hold ? (text as unknown as T) : p.value;
    if (p.hold && !same(v, value)) { sent.current = { v }; onValue(v); }
    onCommit?.(p.hold ? v : value);
  }

  return (
    <input
      type="text"
      {...rest}
      value={text}
      onChange={(e) => {
        const t = e.target.value;
        setText(t);
        const p = parse(t);
        if (p.hold) return;
        sent.current = { v: p.value };
        onValue(p.value);
      }}
      onBlur={(e) => { commit(); onBlur?.(e); }}
      onKeyDown={(e) => { if (e.key === 'Enter') commit(); onKeyDown?.(e); }}
    />
  );
}

// a number field that can be typed key by key; text that is not a number is passed on as it is, so it can be flagged
export function numberParse(emptyAs: any = ''): (t: string) => Parsed<any> {
  return (t: string) => {
    const d = numberDraft(t);
    if (d.kind === 'number') return { value: d.value };
    if (d.kind === 'empty') return { value: emptyAs };
    if (d.kind === 'partial') return { hold: true };
    return { value: t };
  };
}

export function numberFormat(v: any): string {
  return v === undefined || v === null ? '' : String(v);
}

type NumberProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type'> & {
  value: any;
  onValue: (v: any) => void;
  onCommit?: (v: any) => void;
  emptyAs?: any;
};

export function NumberInput({ value, onValue, onCommit, emptyAs = '', ...rest }: NumberProps) {
  return <DraftInput value={value} format={numberFormat} parse={numberParse(emptyAs)} onValue={onValue} onCommit={onCommit} inputMode="decimal" {...rest} />;
}
