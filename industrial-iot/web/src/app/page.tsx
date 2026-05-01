'use client';

import { useState } from 'react';
import { Activity, Layers, Thermometer } from 'lucide-react';
import PumpTab from './tabs/PumpTab';
import ColdChainTab from './tabs/ColdChainTab';
import ArchitectureTab from './tabs/ArchitectureTab';

type TabKey = 'pump' | 'coldchain' | 'architecture';

const TABS: { key: TabKey; label: string; icon: typeof Activity; desc: string }[] = [
  { key: 'pump',         label: 'Pump Vibration',  icon: Activity,    desc: 'Predictive maintenance on rotating machinery' },
  { key: 'coldchain',    label: 'Cold Chain',      icon: Thermometer, desc: 'Reefer-container FSMA excursion monitoring'   },
  { key: 'architecture', label: 'Architecture',    icon: Layers,      desc: 'How it all fits together'                       },
];

export default function IndustrialIotPage() {
  const [tab, setTab] = useState<TabKey>('pump');

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Industrial IoT</h1>
        <p className="text-sm text-slate-400 mt-1">
          Two end-to-end industrial showcases riding the same platform —
          uploaded Go / Python runs in sandboxed k8s Jobs, LLM reasoning
          interprets the signals, pipelines fan out alerts and work orders.
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-800">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-cyan-400 text-white'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}>
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      <div>
        {tab === 'pump'         && <PumpTab />}
        {tab === 'coldchain'    && <ColdChainTab />}
        {tab === 'architecture' && <ArchitectureTab />}
      </div>
    </div>
  );
}
