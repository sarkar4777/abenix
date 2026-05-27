'use client';

import { Flame } from 'lucide-react';
import { CommodityHub } from '../_hub';

export default function GasHubPage() {
  return (
    <CommodityHub cfg={{
      slug: 'gas',
      title: 'Natural Gas',
      subtitle: 'Hubs: TTF · THE · CEGH · PSV · PEG · NBP. Storage, send-out, pipeline flows, retail offtake.',
      accent: 'orange',
      icon: Flame,
      hubs: [
        { name: 'TTF M+1',  spot: 34.82, unit: '€/MWh', change:  0.62 },
        { name: 'THE M+1',  spot: 35.04, unit: '€/MWh', change:  0.41 },
        { name: 'CEGH M+1', spot: 35.21, unit: '€/MWh', change:  0.18 },
        { name: 'PSV M+1',  spot: 35.78, unit: '€/MWh', change:  0.71 },
      ],
      curve: [
        { tenor: 'M+1', mid: 34.82 },
        { tenor: 'M+2', mid: 35.10 },
        { tenor: 'Q+1', mid: 36.20 },
        { tenor: 'Q+2', mid: 34.50 },
        { tenor: 'Cal+1', mid: 33.40 },
        { tenor: 'Cal+2', mid: 32.10 },
      ],
      signals: [
        { id: 's1', severity: 'high', text: 'TTF M+1 vs Q1 spread €7.4 above 5y avg — storage cycling rec live.' },
        { id: 's2', severity: 'warn', text: 'HDD next 7 days +14% vs norm — residential offtake forecast lifted.' },
        { id: 's3', severity: 'info', text: 'CEGH-TTF basis tightening to €0.39 — favours HU storage.' },
      ],
      contracts: [
        { id: 'GAS-2024-118', cp: 'OMV Trading', vol: '120 GWh/Q1', status: 'active' },
        { id: 'GAS-2024-094', cp: 'RWE Supply', vol: '500 GWh/Cal',  status: 'active' },
        { id: 'GAS-2025-007', cp: 'EnBW Trading', vol: '85 GWh/M',  status: 'pending' },
      ],
      glossary: [
        { term: 'TTF / THE / CEGH / PSV', def: 'European gas pricing hubs. TTF (Netherlands) is the benchmark; THE (Germany merged), CEGH (Austria), PSV (Italy) trade as basis to TTF.' },
        { term: 'Storage cycling',         def: 'P&L from injecting gas during summer (cheap) and withdrawing in winter (expensive). The spread between front-month and winter prices drives the trade.' },
        { term: 'Linepack',                def: 'Gas pressurised inside a pipeline acting as short-term flexibility. When linepack is tight, system operators raise balancing prices to force adjustments.' },
      ],
    }} />
  );
}
