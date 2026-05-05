'use client';

import { useState } from 'react';
import { Activity, Layers, Thermometer, Wind, Wrench, ShieldAlert } from 'lucide-react';
import PumpTab from './tabs/PumpTab';
import ColdChainTab from './tabs/ColdChainTab';
import ArchitectureTab from './tabs/ArchitectureTab';
import ValueEdgeTab from './tabs/ValueEdgeTab';
import FieldEdgeTab from './tabs/FieldEdgeTab';
import BedRoccTab from './tabs/BedRoccTab';

type TabKey = 'pump' | 'coldchain' | 'valueedge' | 'fieldedge' | 'bedrocc' | 'architecture';

const TABS: { key: TabKey; label: string; icon: typeof Activity; desc: string }[] = [
  { key: 'pump',         label: 'Pump Vibration',  icon: Activity,     desc: 'Predictive maintenance on rotating machinery' },
  { key: 'coldchain',    label: 'Cold Chain',      icon: Thermometer,  desc: 'Reefer-container FSMA excursion monitoring'   },
  { key: 'valueedge',    label: 'Design Studio',   icon: Wind,         desc: 'Engineering & EPC copilot — site brief to ranked designs' },
  { key: 'fieldedge',    label: 'Field Guide',     icon: Wrench,       desc: 'Wind-farm maintenance copilot + scheduler' },
  { key: 'bedrocc',      label: 'Alarm Desk',      icon: ShieldAlert,  desc: 'Operations control-room alarm triage' },
  { key: 'architecture', label: 'Architecture',    icon: Layers,       desc: 'How it all fits together' },
];

export default function IndustrialIotPage() {
  const [tab, setTab] = useState<TabKey>('pump');

  return (
    <div className="max-w-7xl mx-auto px-6 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Industrial IoT</h1>
        <p className="text-sm text-slate-400 mt-1">
          Five end-to-end industrial showcases riding the same platform —
          sandboxed Go/Python in k8s Jobs, LLM reasoning over the signals,
          pipelines fanning out alerts, work orders, designs, and shift reports.
        </p>
      </div>

      <div className="flex gap-1 border-b border-slate-800 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
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
        {tab === 'valueedge'    && <ValueEdgeTab />}
        {tab === 'fieldedge'    && <FieldEdgeTab />}
        {tab === 'bedrocc'      && <BedRoccTab />}
        {tab === 'architecture' && <ArchitectureTab />}
      </div>
    </div>
  );
}
