'use client';

import { Zap } from 'lucide-react';
import { CommodityHub } from '../_hub';

export default function PowerHubPage() {
  return (
    <CommodityHub cfg={{
      slug: 'power',
      title: 'Power',
      subtitle: 'Hubs: DE · HU · PL · CZ · IT · FR · Nordic. Day-ahead, intraday, balancing, clean-spark spreads.',
      accent: 'amber',
      icon: Zap,
      hubs: [
        { name: 'DE Cal+1', spot:  95.6, unit: '€/MWh', change: -1.20 },
        { name: 'HU Cal+1', spot: 113.0, unit: '€/MWh', change:  0.85 },
        { name: 'PL Cal+1', spot:  90.4, unit: '€/MWh', change:  0.32 },
        { name: 'IT Cal+1', spot: 108.2, unit: '€/MWh', change:  1.10 },
      ],
      curve: [
        { tenor: 'M+1', mid:  92.5 },
        { tenor: 'M+2', mid:  94.3 },
        { tenor: 'Q+1', mid:  98.7 },
        { tenor: 'Q+2', mid:  90.4 },
        { tenor: 'Cal+1', mid:  95.6 },
        { tenor: 'Cal+2', mid:  92.1 },
      ],
      signals: [
        { id: 's1', severity: 'warn', text: 'DE wind 7d forecast +18% vs norm — DE-Power Cal+1 ML fair-value 1.8σ short signal.' },
        { id: 's2', severity: 'info', text: 'EUA at €87/t — clean-spark spread +€18 supports gas-fired dispatch.' },
        { id: 's3', severity: 'info', text: 'BESS dispatch revenue Q1 +€420k vs Q4 baseline.' },
      ],
      contracts: [
        { id: 'PWR-2024-073', cp: 'Iberdrola',    vol: '8 MW × 8760h', status: 'active' },
        { id: 'PWR-2024-088', cp: 'Vattenfall',   vol: '12 MW × 720h', status: 'active' },
        { id: 'PWR-2025-002', cp: 'Statkraft',    vol: '5 MW × 4380h', status: 'draft'  },
      ],
      glossary: [
        { term: 'Clean-spark spread', def: 'The margin a gas-fired plant earns: power price minus (gas price × heat rate) minus (EUA price × emission rate). When clean-spark is positive, gas plants run profitably.' },
        { term: 'Day-ahead / intraday / balancing', def: 'Three power markets: day-ahead clears the next 24h at noon; intraday runs continuously up to delivery; balancing settles deviations in real-time.' },
        { term: 'BESS', def: 'Battery Energy Storage System. Charges when power is cheap, discharges when expensive; also earns from balancing-reserve auctions.' },
      ],
    }} />
  );
}
