import { describe, expect, it } from 'vitest';
import { defaultSignals, parseSignals } from '@/lib/telemetry/charts';
import { liveRate, niceRange } from '@/lib/telemetry/format';
import { findGaps } from '@/components/telemetry/HistoryChart';

const m = (name: string, value: number | string | boolean = 1) => ({ name, value });
const moving = (n = 5) => Array.from({ length: n }, (_, i) => ({ t: i * 1000, v: i }));
const flat = (n = 5) => Array.from({ length: n }, (_, i) => ({ t: i * 1000, v: 7 }));

describe('default chart signals', () => {
  it('opens an engine on speed and coolant, not on bus counters', () => {
    const list = [m('Bus/Frames'), m('Diagnostics/ActiveCount'), m('Engine/Coolant_c'), m('Engine/Speed_rpm'), m('Engine/Load_pct'), m('ECU/Address')];
    expect(defaultSignals(list, undefined)).toEqual(['Engine/Speed_rpm', 'Engine/Coolant_c', 'Engine/Load_pct']);
  });
  it('picks pressure for hydraulics, voltage and power for a meter, position for GPS', () => {
    expect(defaultSignals([m('Hydraulics/OilTemp_c'), m('Hydraulics/BoomPressure_bar'), m('Hydraulics/Pump1_bar')], undefined, 2)).toEqual(['Hydraulics/BoomPressure_bar', 'Hydraulics/OilTemp_c']);
    expect(defaultSignals([m('meter/frequency_hz'), m('meter/voltage_v'), m('meter/power_kw')], undefined, 2)).toEqual(['meter/power_kw', 'meter/voltage_v']);
    expect(defaultSignals([m('gps/hdop'), m('gps/lat'), m('gps/speed_kmh')], undefined, 2)).toEqual(['gps/speed_kmh', 'gps/lat']);
  });
  it('puts a flat line last and skips text and flags', () => {
    const list = [m('Engine/Speed_rpm'), m('Engine/Coolant_c'), m('Task/State', 'dig'), m('Safety/Hold', false)];
    expect(defaultSignals(list, { 'Engine/Speed_rpm': flat(), 'Engine/Coolant_c': moving() }, 2)).toEqual(['Engine/Coolant_c', 'Engine/Speed_rpm']);
  });
  it('reads the signals link parameter', () => {
    expect(parseSignals('Engine/Speed_rpm, Engine/Coolant_c,,')).toEqual(['Engine/Speed_rpm', 'Engine/Coolant_c']);
    expect(parseSignals(null)).toEqual([]);
    expect(parseSignals('a,b,c,d,e,f,g')).toHaveLength(6);
  });
});

describe('live rate and gaps', () => {
  it('never shows a bare 0 for a live source that batches', () => {
    expect(liveRate(12, 300, true)).toEqual({ value: '12', unit: 'msg/s' });
    expect(liveRate(0.5, 23, true)).toEqual({ value: '23', unit: 'readings/s' });
    expect(liveRate(0.5, null, true)).toEqual({ value: '0.5', unit: 'msg/s' });
    expect(liveRate(0, 0, true)).toEqual({ value: 'under 1', unit: 'msg/s' });
    expect(liveRate(40, 900, false)).toEqual({ value: '0', unit: 'msg/s' });
  });
  it('finds the stretch with no data', () => {
    const pts = [0, 1000, 2000, 3000, 120000, 121000].map((t) => ({ t, v: 1 }));
    expect(findGaps(pts)).toEqual([{ from: 3000, to: 120000 }]);
  });
});

describe('chart axis', () => {
  it('never goes below 0 for values that never do', () => {
    const [lo] = niceRange([0, 2.5, 14, 22], null, 'L/h');
    expect(lo).toBe(0);
    expect(niceRange([-3, 5], null, '°C')[0]).toBeLessThan(0);
  });
  it('stops percentages at 100 with round steps', () => {
    expect(niceRange([0, 40, 97], null, '%')).toEqual([0, 100]);
    const [lo, hi] = niceRange([30, 62], null, '%');
    expect(lo).toBeGreaterThanOrEqual(0);
    expect(hi).toBeLessThanOrEqual(100);
    expect(niceRange([10, 130], null, '%')[1]).toBeGreaterThan(100);
  });
  it('keeps the clamp when it holds the previous range', () => {
    expect(niceRange([20, 80], [-20, 120], '%')).toEqual([0, 100]);
  });
});
