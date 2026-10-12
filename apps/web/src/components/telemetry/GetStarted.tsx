'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ArrowRight, CircuitBoard, Code2, Compass, Factory, Plug, Radio, Truck, Wrench } from 'lucide-react';
import ResponsiveModal from '@/components/ui/ResponsiveModal';
import { GUIDE, edgeHref, type GuideCategory, type GuidePath } from '@/lib/telemetry/guide';
import type { TransportDecl } from '@/lib/telemetry/sources';
import { TransportIcon } from './transportIcon';
import type { WizardStart } from './SourceWizard';

const ICONS = { truck: Truck, factory: Factory, sensor: Radio, plug: Plug, code: Code2 };

function PathCard({ p, canManage, available, onSource }: { p: GuidePath; canManage: boolean; available: boolean; onSource: (s: WizardStart) => void }) {
  const a = p.action;
  return (
    <li className="rounded-lg border border-slate-700 p-3" data-testid="tel-guide-path" data-path={p.id}>
      <div className="flex items-start gap-2">
        {a.kind === 'edge' ? <CircuitBoard className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" /> : <TransportIcon transport={a.kind === 'source' ? a.transport : 'http_push'} className="mt-0.5 h-4 w-4 shrink-0 text-cyan-300" />}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-white">{p.title}</p>
          <p className="mt-0.5 text-xs text-slate-300">{p.text}</p>
          {p.code && (
            <p className="mt-1.5 flex items-start gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-xs text-amber-100" data-testid="tel-guide-code">
              <Wrench className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {p.code}
            </p>
          )}
          <div className="mt-2">
            {!canManage ? (
              <p className="text-xs text-slate-400">An admin sets this up under Telemetry, Sources. Send them this page.</p>
            ) : a.kind === 'edge' ? (
              <Link href={edgeHref(a.collector)} className="inline-flex items-center gap-1 text-xs font-medium text-cyan-300 hover:underline" data-testid="tel-guide-edge">
                Add an edge gateway <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            ) : a.kind === 'source' && !available ? (
              <p className="text-xs text-slate-400">This server does not have the {a.transport} connector yet. An admin can update Abenix to add it.</p>
            ) : a.kind === 'source' ? (
              <button
                type="button"
                onClick={() => onSource({ transport: a.transport, decoder: a.decoder, name: a.name, mapping: a.mapping, sample: a.sample, subject: a.subject, config: a.config })}
                className="inline-flex items-center gap-1 rounded-md bg-cyan-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-cyan-400"
                data-testid="tel-guide-start"
              >
                Set it up <ArrowRight className="h-3.5 w-3.5" />
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </li>
  );
}

// "What do you want to connect?", then the ways in for that kind of thing
export default function GetStarted({ open, onClose, canManage, transports, onSource }: {
  open: boolean; onClose: () => void; canManage: boolean; transports: TransportDecl[] | null; onSource: (s: WizardStart) => void;
}) {
  const [cat, setCat] = useState<GuideCategory | null>(null);
  const have = (t: string) => !transports || transports.some((x) => x.transport === t);
  return (
    <ResponsiveModal open={open} onClose={onClose} title={cat ? cat.title : 'Get started'} icon={<Compass className="h-4 w-4" />} maxWidth="max-w-3xl">
      <div className="space-y-4" data-testid="tel-guide" data-step={cat ? cat.id : 'pick'}>
        {!cat ? (
          <>
            <div>
              <h3 className="text-base font-semibold text-white">What do you want to connect?</h3>
              <p className="mt-1 text-sm text-slate-300">Pick the closest match. Each one shows the ways in, in plain words, and ends with live data on this page. Most need nothing installed. Where something has to run on your side, it says so and why.</p>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {GUIDE.map((c) => {
                const Icon = ICONS[c.icon];
                return (
                  <button key={c.id} type="button" onClick={() => setCat(c)} className="flex items-start gap-3 rounded-lg border border-slate-700 p-3 text-left hover:border-cyan-500/60" data-testid={`tel-guide-${c.id}`}>
                    <Icon className="mt-0.5 h-5 w-5 shrink-0 text-cyan-300" />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-white">{c.title}</span>
                      <span className="mt-0.5 block text-xs text-slate-400">{c.examples}</span>
                    </span>
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-slate-500">Something else? Any system that can call a web address can post data, see Software systems, From your own code.</p>
          </>
        ) : (
          <>
            <button type="button" onClick={() => setCat(null)} className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-cyan-300" data-testid="tel-guide-back">
              <ArrowLeft className="h-3 w-3" /> Something else
            </button>
            <p className="text-sm text-slate-300">Ways to bring in {cat.title.toLowerCase()}, quickest first.</p>
            <ol className="space-y-2">
              {cat.paths.map((p) => (
                <PathCard key={p.id} p={p} canManage={canManage} available={p.action.kind !== 'source' || have(p.action.transport)} onSource={(s) => { onSource(s); onClose(); }} />
              ))}
            </ol>
          </>
        )}
      </div>
    </ResponsiveModal>
  );
}
