'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Bell, Bot, Boxes, ExternalLink, Scale, Sparkles, Workflow, X } from 'lucide-react';

const KEY = 'telemetry.whatNext.hidden';

export const GROUNDWORK_REPO = 'https://github.com/sarkar4777/groundwork';

const ITEMS = [
  { id: 'rules', icon: Bell, title: 'Act when a signal crosses a line', text: 'Rules watch signals as they arrive and raise an alert, notify someone, run an agent or send a command.', href: '/telemetry/rules/new', cta: 'Make a rule' },
  { id: 'agent', icon: Bot, title: 'Let an agent watch your assets', text: 'Start from a template: machine health watcher, fleet dispatcher, anomaly triage or shift reporter. Each is made in one click and reads live values and history.', href: '/telemetry/agents', cta: 'Pick a template' },
  { id: 'pipeline', icon: Workflow, title: 'Run a pipeline on the data', text: 'Chain steps, for example read the last hour, find outliers and write a shift report. Pick Pipeline in the builder.', href: '/builder', cta: 'Open the builder' },
  { id: 'decision', icon: Scale, title: 'Put your limits in a decision table', text: 'Keep thresholds and what to do about them in a table people can sign off, and call it from rules and agents.', href: '/decisions', cta: 'Open Decisions' },
  { id: 'twin', icon: Boxes, title: 'Model it as a twin', text: 'Upload your own simulation or twin as a code asset and feed it live values each step.', href: '/code-runner', cta: 'Open Code Runner' },
];

// shown once data flows, the ways to build on it
export default function WhatNext() {
  const [hidden, setHidden] = useState(true);
  useEffect(() => {
    try { setHidden(localStorage.getItem(KEY) === '1'); } catch { setHidden(false); }
  }, []);
  if (hidden) return null;
  const hide = () => {
    setHidden(true);
    try { localStorage.setItem(KEY, '1'); } catch { /* storage blocked, it comes back next visit */ }
  };
  return (
    <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4" aria-label="What next" data-testid="tel-what-next">
      <div className="mb-3 flex items-start gap-2">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-emerald-100">Data is flowing. What next?</h2>
          <p className="text-xs text-slate-300">
            Groundwork is a worked example: a construction site twin whose machines stream here, with rules, agents and safety holds built on top.{' '}
            <a href={GROUNDWORK_REPO} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-cyan-300 hover:underline">See how it is built <ExternalLink className="h-3 w-3" /></a>
          </p>
        </div>
        <button type="button" onClick={hide} aria-label="Hide What next" title="Hide this. It stays hidden on this browser." className="rounded p-1 text-slate-400 hover:text-white" data-testid="tel-what-next-hide"><X className="h-4 w-4" /></button>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {ITEMS.map((i) => {
          const Icon = i.icon;
          return (
            <li key={i.id} className="flex flex-col rounded-lg border border-slate-700/60 bg-slate-900/40 p-3" data-testid={`tel-next-${i.id}`}>
              <Icon className="h-4 w-4 text-cyan-300" />
              <p className="mt-1 text-sm font-medium text-white">{i.title}</p>
              <p className="mt-0.5 flex-1 text-xs text-slate-400">{i.text}</p>
              <span className="mt-2 flex flex-wrap gap-x-3 text-xs">
                <Link href={i.href} className="font-medium text-cyan-300 hover:underline">{i.cta}</Link>
                {i.id === 'rules' && <Link href="/telemetry/rules" className="text-slate-400 hover:text-cyan-300 hover:underline">See all rules</Link>}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
