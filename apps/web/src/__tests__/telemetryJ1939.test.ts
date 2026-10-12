import { describe, expect, it } from 'vitest';
import { BamAssembler, decodeFrame, parseCanId, toBytes, type DecodedFrame } from '@/lib/telemetry/j1939';

// vectors made with the Groundwork twin's own J1939 encoder
const frame = (id: number, hex: string, t = 1760000000.25): DecodedFrame => decodeFrame({ t, id, data: toBytes(hex), dlc: 8 });
const sig = (f: DecodedFrame, key: string) => f.signals.find((s) => s.key === key)?.value;

describe('J1939 identifiers', () => {
  it('splits a PDU2 id into priority, PGN and source', () => {
    expect(parseCanId(0x0cf00400)).toEqual({ priority: 3, pgn: 61444, sa: 0, da: 0xff });
    expect(parseCanId(0x18fef317)).toEqual({ priority: 6, pgn: 65267, sa: 0x17, da: 0xff });
  });
  it('keeps the destination out of a PDU1 PGN', () => {
    expect(parseCanId(0x1cecff2a)).toEqual({ priority: 7, pgn: 60416, sa: 0x2a, da: 0xff });
    expect(parseCanId(0x18ea0017).pgn).toBe(59904);
    expect(parseCanId(0x18ea0017).da).toBe(0);
  });
});

describe('PGN decoders', () => {
  it('EEC1 engine speed and torque', () => {
    const f = frame(0x0cf00400, 'F1A5A7542D00F0AA');
    expect(f.acronym).toBe('EEC1');
    expect(sig(f, 'engine_speed_rpm')).toBe(1450.5);
    expect(sig(f, 'actual_torque_pct')).toBe(42);
    expect(sig(f, 'drivers_demand_torque_pct')).toBe(40);
    expect(sig(f, 'engine_demand_torque_pct')).toBe(45);
    expect(f.summary).toContain('Engine speed 1450.5 rpm');
    expect(f.ms).toBe(1760000000250);
  });
  it('ET1 temperatures, with not available left out', () => {
    const f = frame(0x18feee00, '8051502EFFFF5FFF');
    expect(sig(f, 'coolant_c')).toBe(88);
    expect(sig(f, 'fuel_temp_c')).toBe(41);
    expect(sig(f, 'oil_temp_c')).toBe(97.5);
    expect(sig(f, 'intercooler_c')).toBe(55);
    expect(sig(f, 'turbo_oil_temp_c')).toBeNull();
    expect(f.summary).not.toContain('Turbo');
  });
  it('LFE1 fuel rate and throttle', () => {
    const f = frame(0x18fef200, 'D501FFFFFFFF9CFF');
    expect(sig(f, 'fuel_rate_lph')).toBe(23.45);
    expect(sig(f, 'throttle_pct')).toBe(62.4);
    expect(sig(f, 'inst_fuel_economy_kmpl')).toBeNull();
  });
  it('VP latitude and longitude', () => {
    const f = frame(0x18fef317, '78D3BE8B48C6949D');
    expect(f.sa).toBe(0x17);
    expect(sig(f, 'latitude_deg')).toBeCloseTo(24.4539, 6);
    expect(sig(f, 'longitude_deg')).toBeCloseTo(54.3773, 6);
  });
  it('VDS bearing, speed, pitch and altitude', () => {
    const f = frame(0x18fee817, 'C087400C4062804E');
    expect(sig(f, 'compass_bearing_deg')).toBe(271.5);
    expect(sig(f, 'nav_speed_kmh')).toBe(12.25);
    expect(sig(f, 'pitch_deg')).toBe(-3.5);
    expect(sig(f, 'altitude_m')).toBe(12);
  });
  it('ETC2 gears and ratio', () => {
    const f = frame(0x18f00503, '80290980FFFFFFFF');
    expect(f.acronym).toBe('ETC2');
    expect(sig(f, 'selected_gear')).toBe(3);
    expect(sig(f, 'current_gear')).toBe(3);
    expect(sig(f, 'actual_gear_ratio')).toBe(2.345);
  });
  it('CCVS1 wheel speed and the parking brake as a word', () => {
    const f = frame(0x18fef10b, 'F78012FFFFFFFFFF');
    expect(sig(f, 'wheel_speed_kmh')).toBe(18.5);
    expect(f.signals.find((s) => s.key === 'parking_brake')?.text).toBe('on');
  });
  it('HOURS engine hours and revolutions', () => {
    const f = frame(0x18fee500, '7360000088130000');
    expect(sig(f, 'engine_hours')).toBe(1234.55);
    expect(sig(f, 'engine_revolutions')).toBe(5000000);
  });
  it('DM1 with one active fault names the SPN and FMI in words', () => {
    const f = frame(0x18feca00, '04FF6E000003FFFF');
    expect(f.acronym).toBe('DM1');
    expect(f.dm1?.lamps.amber_warning).toBe(1);
    expect(f.dm1?.dtcs).toEqual([expect.objectContaining({ spn: 110, fmi: 0, oc: 3, spnText: 'Engine coolant temperature' })]);
    expect(f.summary).toMatch(/^1 active fault, lamps: amber warning\. Engine coolant temperature \(SPN 110 FMI 0\)/);
  });
  it('DM1 with no fault says so', () => {
    expect(frame(0x18feca00, '00FF00000000FFFF').summary).toBe('No active faults, no lamps on');
  });
  it('reassembles a DM1 sent over BAM', () => {
    const bam = new BamAssembler();
    const a = bam.push(frame(0x1cecff2a, '200A0002FFCAFE00'));
    expect(a.summary).toBe('Announces DM1, 10 bytes in 2 packets');
    bam.push(frame(0x1cebff2a, '0110FF6E00000308'));
    const last = bam.push(frame(0x1cebff2a, '02F0F001FFFFFFFF'));
    expect(last.acronym).toBe('DM1');
    expect(last.dm1?.lamps.red_stop).toBe(1);
    expect(last.dm1?.dtcs.map((d) => [d.spn, d.fmi, d.oc])).toEqual([[110, 0, 3], [520200, 16, 1]]);
  });
  it('labels proprietary and unknown PGNs instead of guessing', () => {
    expect(frame(0x10ff1000, '0102030405060708').summary).toBe('Proprietary B, maker specific');
    expect(frame(0x18fe6c00, '0102030405060708').acronym).toBeNull();
  });
  it('reads hex with spaces, a 0x prefix, or a byte list', () => {
    expect(toBytes('0x0A 1b 2C')).toEqual([10, 27, 44]);
    expect(toBytes([255, 256])).toEqual([255, 0]);
    expect(toBytes(null)).toEqual([]);
  });
});
