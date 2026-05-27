'use client';

import { Ship } from 'lucide-react';
import { CommodityHub } from '../_hub';

export default function LngHubPage() {
  return (
    <CommodityHub cfg={{
      slug: 'lng',
      title: 'LNG',
      subtitle: 'Regas terminals · slot calendars · cargo book · Henry-TTF basis · vessel deployment.',
      accent: 'sky',
      icon: Ship,
      hubs: [
        { name: 'JKM M+1',    spot: 12.84, unit: '$/MMBtu', change:  0.42 },
        { name: 'TTF (Mbtu)', spot: 10.55, unit: '$/MMBtu', change:  0.18 },
        { name: 'Henry M+1',  spot:  3.21, unit: '$/MMBtu', change: -0.05 },
        { name: 'NBP M+1',    spot: 10.62, unit: '$/MMBtu', change:  0.21 },
      ],
      curve: [
        { tenor: 'M+1', mid: 12.84 },
        { tenor: 'M+2', mid: 13.10 },
        { tenor: 'Q+1', mid: 13.85 },
        { tenor: 'Q+2', mid: 12.40 },
        { tenor: 'Cal+1', mid: 12.10 },
        { tenor: 'Cal+2', mid: 11.20 },
      ],
      signals: [
        { id: 's1', severity: 'high', text: 'Krk Q1 slots fully booked — pre-sell 2 cargoes Q2 implied PV +€310k.' },
        { id: 's2', severity: 'info', text: 'Henry-TTF basis $+2.10 — US arbitrage stable for next 90 days.' },
        { id: 's3', severity: 'warn', text: 'Brunsbüttel maintenance Nov 12-26 — diverts cargoes to Spanish terminals.' },
      ],
      contracts: [
        { id: 'LNG-2024-003', cp: 'Cheniere',    vol: '12 cargoes/Cal', status: 'active' },
        { id: 'LNG-2024-005', cp: 'Equinor',     vol: '4 cargoes/Q1',   status: 'active' },
        { id: 'LNG-2025-001', cp: 'Venture Glob',vol: '8 cargoes/Cal',  status: 'pending'},
      ],
      glossary: [
        { term: 'JKM',          def: 'Japan-Korea Marker — the Asian LNG benchmark. JKM-TTF arbitrage determines whether cargoes route to Asia or Europe.' },
        { term: 'Regas slot',   def: 'A booked timeslot at an LNG import terminal where a vessel can dock + unload. Slot calendars are scarce; bookings extend years out.' },
        { term: 'Send-out',     def: 'The rate at which an LNG terminal regasifies and feeds the gas grid. Subject to TSO nomination + slot calendar.' },
      ],
    }} />
  );
}
