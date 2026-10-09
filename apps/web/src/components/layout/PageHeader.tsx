'use client';

import { isValidElement, useEffect, useRef, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { ArrowLeft, BookOpen, ChevronDown, ChevronRight, HelpCircle, type LucideIcon } from 'lucide-react';

export interface HeaderAction {
  label: string;
  href?: string;
  onClick?: () => void;
  icon?: LucideIcon;
  disabled?: boolean;
  // tooltip, also says why a button is disabled
  title?: string;
  testId?: string;
  external?: boolean;
  busy?: boolean;
}

export type HowStep = ReactNode | { title: ReactNode; body?: ReactNode };

export interface PageHeaderProps {
  title: ReactNode;
  purpose: ReactNode;
  icon?: LucideIcon;
  iconClassName?: string;
  primaryAction?: HeaderAction | ReactNode;
  secondaryAction?: HeaderAction | ReactNode;
  // anything small that sits next to the actions, like a refresh button
  extraActions?: ReactNode;
  steps?: HowStep[];
  // extra text under the steps
  howItWorks?: ReactNode;
  docSlug?: string;
  storageKey?: string;
  back?: { href: string; label: string };
  // badges next to the title
  meta?: ReactNode;
  titleTestId?: string;
  howTestId?: string;
  howToggleTestId?: string;
  children?: ReactNode;
  className?: string;
  // one short row for full height tool pages, how-it-works starts shut
  compact?: boolean;
}

export const docHref = (slug: string) => `/docs?doc=${encodeURIComponent(slug)}`;

function storageId(key: string) {
  return `pageHeader.how.${key}`;
}

// '1' collapsed, '0' open, missing means first visit
export function readHowState(key: string): '1' | '0' | null {
  try {
    const v = localStorage.getItem(storageId(key));
    return v === '1' || v === '0' ? v : null;
  } catch {
    return null;
  }
}

function writeHowState(key: string, collapsed: boolean) {
  try {
    localStorage.setItem(storageId(key), collapsed ? '1' : '0');
  } catch {
    // storage blocked, the panel just opens again next time
  }
}

function slugKey(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'page';
}

function isAction(a: unknown): a is HeaderAction {
  return !!a && typeof a === 'object' && !isValidElement(a) && 'label' in (a as object);
}

const BASE = 'inline-flex min-h-[40px] w-full items-center justify-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors sm:w-auto disabled:cursor-not-allowed disabled:opacity-50';
const PRIMARY = `${BASE} bg-cyan-500 text-white hover:bg-cyan-400`;
const SECONDARY = `${BASE} border border-slate-700 text-slate-200 hover:bg-slate-800`;
const SMALL = 'inline-flex min-h-[36px] items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50';
const PRIMARY_SM = `${SMALL} bg-cyan-500 text-white hover:bg-cyan-400`;
const SECONDARY_SM = `${SMALL} border border-slate-700 text-slate-200 hover:bg-slate-800`;

function ActionButton({ action, kind, small }: { action: HeaderAction; kind: 'primary' | 'secondary'; small?: boolean }) {
  const cls = small ? (kind === 'primary' ? PRIMARY_SM : SECONDARY_SM) : kind === 'primary' ? PRIMARY : SECONDARY;
  const Icon = action.icon;
  const inner = (
    <>
      {Icon && <Icon className={`h-4 w-4 shrink-0 ${action.busy ? 'animate-spin' : ''}`} />}
      <span className="truncate">{action.label}</span>
    </>
  );
  if (action.href && !action.disabled) {
    if (action.external) {
      return (
        <a href={action.href} target="_blank" rel="noreferrer" className={cls} title={action.title} data-testid={action.testId}>
          {inner}
        </a>
      );
    }
    return (
      <Link href={action.href} className={cls} title={action.title} data-testid={action.testId}>
        {inner}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={action.onClick}
      disabled={action.disabled || action.busy}
      title={action.title}
      className={cls}
      data-testid={action.testId}
    >
      {inner}
    </button>
  );
}

function renderAction(a: HeaderAction | ReactNode, kind: 'primary' | 'secondary', small = false) {
  if (a === null || a === undefined || a === false) return null;
  return isAction(a) ? <ActionButton action={a} kind={kind} small={small} /> : a;
}

function Step({ step, n }: { step: HowStep; n: number }) {
  const rich = !!step && typeof step === 'object' && !isValidElement(step) && 'title' in (step as object);
  const s = step as { title: ReactNode; body?: ReactNode };
  return (
    <li className="flex min-w-0 gap-2.5">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-cyan-500/15 text-[11px] font-semibold text-cyan-300">
        {n}
      </span>
      <div className="min-w-0 break-words">
        {rich ? (
          <>
            <p className="font-medium text-white">{s.title}</p>
            {s.body && <div className="mt-0.5 text-slate-400">{s.body}</div>}
          </>
        ) : (
          <p>{step as ReactNode}</p>
        )}
      </div>
    </li>
  );
}

// The same top block on every page: what this is, who it is for, what to do first.
export default function PageHeader({
  title,
  purpose,
  icon: Icon,
  iconClassName = 'text-cyan-400',
  primaryAction,
  secondaryAction,
  extraActions,
  steps,
  howItWorks,
  docSlug,
  storageKey,
  back,
  meta,
  titleTestId,
  howTestId,
  howToggleTestId,
  children,
  className = '',
  compact = false,
}: PageHeaderProps) {
  const key = storageKey || (typeof title === 'string' ? slugKey(title) : docSlug ? slugKey(docSlug) : 'page');
  const hasHow = (steps && steps.length > 0) || !!howItWorks;
  const [open, setOpen] = useState(!compact);
  const ran = useRef(false);

  useEffect(() => {
    // strict mode runs effects twice, the second run would read our own write
    if (ran.current || !hasHow) return;
    ran.current = true;
    const seen = readHowState(key);
    if (seen === null && compact) {
      setOpen(false);
    } else if (seen === null) {
      // open on the first visit, collapsed after that unless reopened
      writeHowState(key, true);
      setOpen(true);
    } else {
      setOpen(seen === '0');
    }
  }, [key, hasHow, compact]);

  const toggle = () => {
    setOpen((o) => {
      writeHowState(key, o);
      return !o;
    });
  };

  const primary = renderAction(primaryAction, 'primary', compact);
  const secondary = renderAction(secondaryAction, 'secondary', compact);
  const panelId = `how-${key}`;

  const stepList = steps && steps.length > 0 && (
    <ol className={`grid gap-3 ${steps.length >= 3 ? 'sm:grid-cols-2' : ''} ${steps.length === 4 ? 'xl:grid-cols-4' : steps.length === 3 ? 'xl:grid-cols-3' : ''}`}>
      {steps.map((s, i) => (
        <Step key={i} step={s} n={i + 1} />
      ))}
    </ol>
  );

  const docsLink = docSlug && (
    <a
      href={docHref(docSlug)}
      target="_blank"
      rel="noreferrer"
      className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs text-cyan-300 hover:bg-cyan-500/10"
      data-testid="page-docs-link"
    >
      <BookOpen className="h-3.5 w-3.5" /> Docs
    </a>
  );

  if (compact) {
    return (
      <header className={`min-w-0 ${className}`} data-testid="page-header" data-compact="true">
        {back && (
          <Link href={back.href} className="mb-1 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-cyan-400">
            <ArrowLeft className="h-3 w-3" /> {back.label}
          </Link>
        )}
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <div className="min-w-[min(100%,18rem)] flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              {Icon && <Icon className={`h-5 w-5 shrink-0 ${iconClassName}`} aria-hidden />}
              <h1 className="min-w-0 break-words text-lg font-semibold leading-tight text-white" data-testid={titleTestId}>
                {title}
              </h1>
              {meta}
            </div>
            <p className="mt-0.5 max-w-3xl break-words text-xs text-slate-400 sm:text-sm" data-testid="page-purpose">
              {purpose}
            </p>
          </div>
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
            {extraActions}
            {(hasHow || docSlug) && (
              <div className="inline-flex items-center gap-1" data-testid={howTestId || 'page-how-it-works'}>
                {hasHow && (
                  <button
                    type="button"
                    onClick={toggle}
                    aria-expanded={open}
                    aria-controls={panelId}
                    className="inline-flex min-h-[36px] items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                    data-testid={howToggleTestId || 'page-how-toggle'}
                  >
                    <HelpCircle className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
                    How this works
                    {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-400" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-400" />}
                  </button>
                )}
                {docsLink}
              </div>
            )}
            {secondary}
            {primary && (
              <div className="flex min-w-0" data-testid="page-primary-action">
                {primary}
              </div>
            )}
          </div>
        </div>
        {hasHow && open && (
          <div id={panelId} className="mt-2 space-y-3 rounded-xl border border-slate-700/50 bg-slate-800/30 px-4 py-3 text-sm leading-relaxed text-slate-300">
            {stepList}
            {howItWorks}
          </div>
        )}
        {children}
      </header>
    );
  }

  return (
    <header className={`min-w-0 space-y-3 ${className}`} data-testid="page-header">
      {back && (
        <Link href={back.href} className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-cyan-400">
          <ArrowLeft className="h-3 w-3" /> {back.label}
        </Link>
      )}
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1 lg:min-w-[20rem]">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            {Icon && <Icon className={`h-6 w-6 shrink-0 ${iconClassName}`} aria-hidden />}
            <h1 className="min-w-0 break-words text-2xl font-semibold text-white" data-testid={titleTestId}>
              {title}
            </h1>
            {meta}
          </div>
          <p className="mt-1 max-w-3xl break-words text-sm text-slate-400" data-testid="page-purpose">
            {purpose}
          </p>
        </div>
        {(primary || secondary || extraActions) && (
          <div className="flex w-full min-w-0 max-w-full flex-col gap-2 sm:w-auto sm:flex-row sm:flex-wrap sm:items-center lg:shrink-0 lg:justify-end">
            {extraActions}
            {secondary}
            {primary && (
              <div className="flex min-w-0 sm:inline-flex [&>*]:w-full sm:[&>*]:w-auto" data-testid="page-primary-action">
                {primary}
              </div>
            )}
          </div>
        )}
      </div>

      {(hasHow || docSlug) && (
        <section
          className="rounded-xl border border-slate-700/50 bg-slate-800/30"
          data-testid={howTestId || 'page-how-it-works'}
        >
          <div className="flex items-center gap-2 px-4 py-2.5">
            {hasHow ? (
              <button
                type="button"
                onClick={toggle}
                aria-expanded={open}
                aria-controls={panelId}
                className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-medium text-white"
                data-testid={howToggleTestId || 'page-how-toggle'}
              >
                <HelpCircle className="h-4 w-4 shrink-0 text-cyan-400" />
                <span className="flex-1">How this works</span>
                {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
              </button>
            ) : (
              <span className="flex-1" />
            )}
            {docsLink}
          </div>
          {hasHow && open && (
            <div id={panelId} className="space-y-3 border-t border-slate-700/50 px-4 py-3 text-sm leading-relaxed text-slate-300">
              {stepList}
              {howItWorks}
            </div>
          )}
        </section>
      )}
      {children}
    </header>
  );
}
