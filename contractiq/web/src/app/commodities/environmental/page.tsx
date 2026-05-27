'use client';

import { Leaf } from 'lucide-react';
import { CommodityHub } from '../_hub';

export default function EnvironmentalHubPage() {
  return (
    <CommodityHub cfg={{
      slug: 'environmental',
      title: 'Environmental',
      subtitle: 'EU ETS allowances (EUA) · Guarantees of Origin (GoO) · Biomethane certificates · CBAM.',
      accent: 'emerald',
      icon: Leaf,
      hubs: [
        { name: 'EUA Dec-25',      spot:  87.40, unit: '€/t',   change:  1.42 },
        { name: 'GoO Nordic Wind', spot:   3.84, unit: '€/MWh', change:  0.21 },
        { name: 'GoO Solar EU',    spot:   2.91, unit: '€/MWh', change:  0.05 },
        { name: 'Biomethane €/MWh',spot:  62.30, unit: '€/MWh', change: -0.18 },
      ],
      curve: [
        { tenor: 'Dec-24', mid: 86.10 },
        { tenor: 'Dec-25', mid: 87.40 },
        { tenor: 'Dec-26', mid: 92.80 },
        { tenor: 'Dec-27', mid: 98.20 },
        { tenor: 'Dec-28', mid: 104.50 },
        { tenor: 'Dec-29', mid: 110.10 },
      ],
      signals: [
        { id: 's1', severity: 'high', text: 'Bayesian prior for EUA > €100/t in 90 days lifted to 38% (from 22%).' },
        { id: 's2', severity: 'warn', text: 'Auction calendar gap Nov 12-26 — tight supply expected.' },
        { id: 's3', severity: 'info', text: 'GoO Nordic Wind premium over EU Solar widening — biomethane certs steady.' },
      ],
      contracts: [
        { id: 'ENV-2024-014', cp: 'EEX EUA Auction',     vol: '50 kt/Dec-25', status: 'active' },
        { id: 'ENV-2024-022', cp: 'Ørsted GoO',          vol: '120 GWh/Cal',  status: 'active' },
        { id: 'ENV-2025-001', cp: 'Verbio Biomethane',   vol: '8 GWh/M',      status: 'pending'},
      ],
      glossary: [
        { term: 'EUA',          def: 'European Union Allowance — one tonne of CO₂ permitted to be emitted under the EU Emissions Trading System. Industrial + power emitters must surrender one EUA per tonne emitted.' },
        { term: 'GoO',          def: 'Guarantee of Origin — a certificate proving 1 MWh was generated from a specific renewable source. Sold separately from the underlying electricity.' },
        { term: 'Biomethane cert', def: 'A certificate proving 1 MWh of biomethane was injected into the gas grid. Allows fossil-gas buyers to claim renewable equivalence.' },
        { term: 'CBAM',         def: 'Carbon Border Adjustment Mechanism — EU import levy on carbon-intensive goods to prevent leakage. Phasing in from 2026.' },
      ],
    }} />
  );
}
