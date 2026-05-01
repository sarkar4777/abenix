
// ── Shared RNG so streams are reproducible across runs ──────────────
function lcg(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x1_0000_0000;
  };
}

// ── Pump vibration ─────────────────────────────────────────────────
export interface VibrationWindow {
  samples: number[];
  sample_rate_hz: number;
  sensor_id: string;
  shaft_rpm: number;
  scenario: 'healthy' | 'early_bearing_wear' | 'acute_imbalance';
  window_index: number;
}

export function vibrationWindow(i: number, total = 20): VibrationWindow {
  const rnd = lcg(42 + i);
  const sampleRate = 2000;
  const duration = 0.25; // seconds
  const n = Math.floor(sampleRate * duration); // 500 samples

  // Scenario progression: healthy (1-6), early bearing wear (7-12),
  // acute imbalance (13-20).
  let scenario: VibrationWindow['scenario'];
  let bearingAmp = 0;
  let imbalanceAmp = 0.02; // baseline 1x RPM residual
  let noiseAmp = 0.01;
  let kurtosisBoost = 0;

  if (i <= 6) {
    scenario = 'healthy';
  } else if (i <= 12) {
    scenario = 'early_bearing_wear';
    const t = (i - 6) / 6;
    bearingAmp = 0.04 + 0.08 * t;
    noiseAmp = 0.01 + 0.02 * t;
    kurtosisBoost = 0.5 * t; // add occasional impulses
  } else {
    scenario = 'acute_imbalance';
    const t = (i - 12) / (total - 12);
    imbalanceAmp = 0.05 + 0.25 * t;
    bearingAmp = 0.08 + 0.03 * t;
    noiseAmp = 0.02;
    kurtosisBoost = 0.2;
  }

  const shaftRpm = 1800;
  const shaftHz = shaftRpm / 60; // 30 Hz
  const samples: number[] = new Array(n);
  for (let k = 0; k < n; k++) {
    const t = k / sampleRate;
    // 1x RPM imbalance tone
    const imbalance = imbalanceAmp * Math.sin(2 * Math.PI * shaftHz * t);
    // bearing resonance ~ 650 Hz
    const bearing = bearingAmp * Math.sin(2 * Math.PI * 650 * t + rnd() * 6.28);
    // broadband noise
    const noise = noiseAmp * (rnd() - 0.5) * 2;
    // impulsive events for kurtosis (rare large deviations)
    const impulse =
      rnd() < 0.01 * kurtosisBoost ? (rnd() - 0.5) * 0.4 : 0;
    samples[k] = imbalance + bearing + noise + impulse;
  }

  return {
    samples,
    sample_rate_hz: sampleRate,
    sensor_id: 'PUMP-A-01',
    shaft_rpm: shaftRpm,
    scenario,
    window_index: i,
  };
}

// ── Cold-chain reefer trip SF → LA ──────────────────────────────────
export interface ColdChainPoint {
  timestamp: string;
  temp_c: number;
  door_open: boolean;
  lat: number;
  lon: number;
  waypoint_index: number;
  label: string;
}

export interface ColdChainShipment {
  readings: ColdChainPoint[];
  product_spec: {
    sku: string;
    name: string;
    min_c: number;
    max_c: number;
    excursion_minutes: number;
    door_open_minutes: number;
    unit_value_usd: number;
    units_in_shipment: number;
  };
  shipment_context: {
    shipment_id: string;
    carrier: string;
    origin: string;
    destination: string;
    customer_email: string;
    policy_ref: string;
  };
}

export function coldChainShipment(): ColdChainShipment {
  const rnd = lcg(99);
  const start = new Date('2026-04-22T14:00:00Z').getTime();
  const readings: ColdChainPoint[] = [];

  // Great-circle-ish waypoints SF → LA (20 steps, ~5 minutes apart).
  const sfLat = 37.77,
    sfLon = -122.42;
  const laLat = 34.05,
    laLon = -118.24;

  for (let i = 0; i < 20; i++) {
    const frac = i / 19;
    const lat = sfLat + (laLat - sfLat) * frac;
    const lon = sfLon + (laLon - sfLon) * frac;
    const tsMs = start + i * 5 * 60 * 1000;
    const ts = new Date(tsMs).toISOString();
    let temp = 4.5 + (rnd() - 0.5) * 0.4; // baseline ±0.2°C noise around 4.5
    let doorOpen = false;
    let label = 'in_transit';

    if (i === 0) label = 'pickup_sfo';
    if (i === 19) label = 'delivered_lax';

    // Scripted excursion between waypoints 8 and 12 (reefer unit stumble)
    if (i >= 8 && i <= 12) {
      const severity = (i - 7) / 5; // 0.2 → 1.0 → 0.2
      const bell = Math.sin(Math.PI * severity);
      temp = 4.5 + bell * 8.5 + (rnd() - 0.5) * 0.5; // peaks ~13°C
      if (i === 10) label = 'reefer_fault';
    }

    // Door open event at waypoint 15 (intermediate scan) — mild warmup
    if (i === 15) {
      temp = 5.8;
      doorOpen = true;
      label = 'door_scan';
    }
    if (i === 16) {
      temp = 5.2;
      doorOpen = true;
      label = 'door_scan';
    }

    readings.push({
      timestamp: ts,
      temp_c: Math.round(temp * 100) / 100,
      door_open: doorOpen,
      lat: Math.round(lat * 10000) / 10000,
      lon: Math.round(lon * 10000) / 10000,
      waypoint_index: i,
      label,
    });
  }

  return {
    readings,
    product_spec: {
      sku: 'PHARM-A-INSULIN',
      name: 'Insulin vials (refrigerated)',
      min_c: 2.0,
      max_c: 8.0,
      excursion_minutes: 10,
      door_open_minutes: 5,
      unit_value_usd: 120,
      units_in_shipment: 500,
    },
    shipment_context: {
      shipment_id: 'SHP-20260422-001',
      carrier: 'AcmeReefer Logistics',
      origin: 'SFO',
      destination: 'LAX',
      customer_email: 'qa@customer.example',
      policy_ref: 'AR-POL-2024-017',
    },
  };
}
