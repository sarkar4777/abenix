import { describe, expect, it } from 'vitest';
import {
  addTags, assetKey, assetPath, csvPrecheck, draftFromRow, explainAssetError, facetsOf, fieldKeyFrom, filterFromParams, isDirty,
  isFiltered, keyFieldsText, listUrl, locationText, matchAsset, newFieldRow, nextUnregistered, NO_FILTER, pageSlice, parseAssetKey,
  placeServerErrors, replaceRow, sortAssets, statusOf, tagProblem, toPayload, validateDraft, type AssetRow,
} from '@/components/telemetry-rules/assets/lib';

function row(p: Partial<AssetRow>): AssetRow {
  const group = p.group ?? 'fleet';
  const node = p.node ?? 'truck-1';
  const device = p.device ?? '';
  return {
    id: null, key: `${group}/${node}/${device}`, group, node, device, registered: false, display_name: null, type: null, tags: [],
    team_id: null, team_name: null, location: null, fields: {}, live: true, online: true, last_seen: null, connection_id: null,
    parts: [], updated_at: null, can_edit: true, ...p,
  };
}

describe('asset keys', () => {
  it('reads group/node/device with an empty part', () => {
    expect(parseAssetKey('fleet/truck-1/ecu')).toEqual({ group: 'fleet', node: 'truck-1', device: 'ecu' });
    expect(parseAssetKey('fleet/truck-1/')).toEqual({ group: 'fleet', node: 'truck-1', device: '' });
    expect(parseAssetKey('fleet/truck-1')).toEqual({ group: 'fleet', node: 'truck-1', device: '' });
    expect(parseAssetKey('fleet/truck-1/can/0')).toEqual({ group: 'fleet', node: 'truck-1', device: 'can/0' });
    expect(parseAssetKey('fleet')).toBeNull();
    expect(parseAssetKey('/x/y')).toBeNull();
    expect(parseAssetKey('fleet//')).toBeNull();
    expect(assetKey('a', 'b')).toBe('a/b/');
  });
  it('builds the endpoint paths', () => {
    expect(assetPath('g 1', 'n/2', '')).toBe('/api/telemetry/assets/g%201/n%2F2?device=');
    expect(listUrl(NO_FILTER)).toBe('/api/telemetry/assets?limit=5000');
    expect(listUrl({ ...NO_FILTER, parts: true, q: ' van ', status: 'unregistered' }, true)).toBe('/api/telemetry/assets?limit=5000&parts=1&q=van&status=unregistered');
  });
  it('reads filters from the URL and ignores unknown status', () => {
    const p = new URLSearchParams('q=van&type=vehicle&status=bogus&parts=1');
    expect(filterFromParams((k) => p.get(k))).toEqual({ q: 'van', type: 'vehicle', tag: '', status: '', parts: true });
    expect(isFiltered(NO_FILTER)).toBe(false);
    expect(isFiltered({ ...NO_FILTER, parts: true })).toBe(false);
    expect(isFiltered({ ...NO_FILTER, tag: 'x' })).toBe(true);
  });
});

describe('filtering and order', () => {
  const a = row({ node: 'truck-2', registered: true, display_name: 'Truck 2', type: 'vehicle', tags: ['north'], fields: { vin: 'VIN123' }, team_name: 'Depot' });
  const b = row({ node: 'press-1' });
  const part = row({ node: 'truck-2', device: 'ecu' });
  it('matches search, type, tag, status and parts', () => {
    expect(matchAsset(a, { ...NO_FILTER, q: 'vin123' })).toBe(true);
    expect(matchAsset(a, { ...NO_FILTER, q: 'truck depot' })).toBe(true);
    expect(matchAsset(a, { ...NO_FILTER, q: 'press' })).toBe(false);
    expect(matchAsset(a, { ...NO_FILTER, type: 'machine' })).toBe(false);
    expect(matchAsset(a, { ...NO_FILTER, tag: 'North' })).toBe(true);
    expect(matchAsset(a, { ...NO_FILTER, status: 'unregistered' })).toBe(false);
    expect(matchAsset(b, { ...NO_FILTER, status: 'unregistered' })).toBe(true);
    expect(matchAsset(part, NO_FILTER)).toBe(false);
    expect(matchAsset(part, { ...NO_FILTER, parts: true })).toBe(true);
  });
  it('sorts by name with parts under their asset', () => {
    const z = row({ node: 'aaa', registered: true, display_name: 'Zeta' });
    expect(sortAssets([part, z, b, a]).map((r) => `${r.node}/${r.device}`)).toEqual(['press-1/', 'truck-2/', 'truck-2/ecu', 'aaa/']);
  });
  it('counts types and tags', () => {
    expect(facetsOf([a, b, row({ type: 'vehicle', tags: ['north', 'cold'] })])).toEqual({
      types: [{ value: 'vehicle', count: 2 }],
      tags: [{ value: 'cold', count: 1 }, { value: 'north', count: 2 }],
    });
  });
  it('finds the next unnamed asset after the current one', () => {
    const rows = [row({ node: 'a' }), row({ node: 'b', registered: true }), row({ node: 'c' }), row({ node: 'd' })];
    expect(nextUnregistered(rows, 'fleet/a/')).toBe('fleet/c/');
    expect(nextUnregistered(rows, 'fleet/d/')).toBe('fleet/a/');
    expect(nextUnregistered([row({ node: 'a' })], 'fleet/a/')).toBeNull();
    expect(nextUnregistered(rows, null)).toBe('fleet/a/');
  });
  it('replaces a saved row in place and keeps its parts', () => {
    const old = row({ node: 'a', parts: ['ecu'] });
    const out = replaceRow([old, b], { ...old, registered: true, display_name: 'A', parts: undefined });
    expect(out[0].display_name).toBe('A');
    expect(out[0].parts).toEqual(['ecu']);
    expect(replaceRow([b], old)).toEqual([b]);
  });
  it('pages only past 200 rows', () => {
    expect(pageSlice(150, 3)).toEqual({ from: 0, to: 150, pages: 1, page: 0 });
    expect(pageSlice(450, 4)).toEqual({ from: 400, to: 450, pages: 5, page: 4 });
    expect(pageSlice(450, 9)).toEqual({ from: 400, to: 450, pages: 5, page: 4 });
  });
});

describe('formatting', () => {
  it('says where an asset is', () => {
    expect(locationText(null)).toBe('');
    expect(locationText({ lat: 52.370216, lon: 4.895168 })).toBe('52.37022, 4.89517');
    expect(locationText({ x: 12, y: 40.5, label: 'Hall B' })).toBe('Hall B (x 12, y 40.5)');
  });
  it('lists the key details in a fixed order', () => {
    expect(keyFieldsText({ model: 'FH16', vin: 'X1', fleet_no: '7' })).toBe('VIN X1, Model FH16');
    expect(keyFieldsText({})).toBe('');
  });
  it('gives a plain status', () => {
    expect(statusOf({ live: true, online: true }).label).toBe('Online');
    expect(statusOf({ live: true, online: false }).tone).toBe('offline');
    expect(statusOf({ live: false, online: null }).label).toBe('No data yet');
  });
});

describe('tags', () => {
  it('checks each tag', () => {
    expect(tagProblem('north depot')).toBeNull();
    expect(tagProblem('site:a/b-c_d.e')).toBeNull();
    expect(tagProblem('x'.repeat(41))).toMatch(/40 characters/);
    expect(tagProblem('bad#tag')).toMatch(/cannot use/);
    expect(tagProblem(' ')).toMatch(/empty/);
  });
  it('adds from typed text, lower cased and without repeats', () => {
    expect(addTags(['north'], 'North, Cold ,,')).toEqual({ tags: ['north', 'cold'], problem: null });
    const r = addTags([], 'ok, bad!');
    expect(r.tags).toEqual(['ok']);
    expect(r.problem).toMatch(/cannot use/);
    const full = Array.from({ length: 20 }, (_, i) => `t${i}`);
    expect(addTags(full, 'one more').problem).toMatch(/up to 20/);
  });
});

describe('editor draft', () => {
  const saved = row({
    registered: true, display_name: 'Truck 2', type: 'vehicle', tags: ['north'], team_id: 't1', team_name: 'Depot',
    location: { lat: 52.1, lon: 4.2, label: 'Yard' }, fields: { vin: 'VIN1', fleet_no: '7' },
  });

  it('round trips a saved asset without counting as a change', () => {
    const d = draftFromRow(saved);
    expect(d.loc).toBe('gps');
    expect(d.fixed.vin).toBe('VIN1');
    expect(d.custom.map((c) => [c.key, c.value])).toEqual([['fleet_no', '7']]);
    expect(validateDraft(d)).toEqual({});
    expect(isDirty(d, draftFromRow(saved))).toBe(false);
    expect(toPayload(d)).toEqual({
      display_name: 'Truck 2', type: 'vehicle', tags: ['north'], team_id: 't1',
      location: { lat: 52.1, lon: 4.2, label: 'Yard' }, fields: { fleet_no: '7', vin: 'VIN1' },
    });
  });
  it('treats an empty unregistered asset as unchanged and sends nulls', () => {
    const d = draftFromRow(row({}));
    expect(isDirty(d, draftFromRow(row({})))).toBe(false);
    expect(toPayload(d)).toEqual({ display_name: null, type: null, tags: [], team_id: null, location: null, fields: {} });
    expect(isDirty({ ...d, display_name: '  ' }, d)).toBe(false);
    expect(isDirty({ ...d, display_name: 'Press' }, d)).toBe(true);
  });
  it('checks the name and location', () => {
    const d = draftFromRow(row({}));
    expect(validateDraft({ ...d, display_name: 'x'.repeat(121) }).display_name).toMatch(/120 characters/);
    expect(validateDraft({ ...d, loc: 'gps', lat: '91', lon: '' })).toEqual({ lat: expect.stringMatching(/between -90 and 90/), lon: expect.stringMatching(/Enter the longitude/) });
    expect(validateDraft({ ...d, loc: 'gps', lat: '52,3', lon: '4' }).lat).toMatch(/dot for decimals, like 52.3/);
    expect(validateDraft({ ...d, loc: 'site', x: 'abc', y: '1e2' })).toEqual({ x: expect.stringMatching(/must be a number/) });
    expect(toPayload({ ...d, loc: 'site', x: '3', y: '-4.5', label: '' }).location).toEqual({ x: 3, y: -4.5 });
  });
  it('checks custom fields', () => {
    const d = draftFromRow(row({}));
    const r1 = newFieldRow('Fleet No', '7');
    const r2 = newFieldRow('', 'orphan');
    const r3 = newFieldRow('vin', 'x');
    const r4 = newFieldRow('depot', '');
    const r5 = newFieldRow('', '');
    const e = validateDraft({ ...d, custom: [r1, r2, r3, r4, r5] });
    expect(e[`custom.${r1.id}.key`]).toMatch(/lower case/);
    expect(e[`custom.${r2.id}.key`]).toMatch(/Name this field/);
    expect(e[`custom.${r3.id}.key`]).toMatch(/own box/);
    expect(e[`custom.${r4.id}.value`]).toMatch(/Give it a value/);
    expect(Object.keys(e).some((k) => k.includes(r5.id))).toBe(false);
    expect(fieldKeyFrom('Fleet No-2')).toBe('fleet_no_2');
    const dup = validateDraft({ ...d, custom: [newFieldRow('a', '1'), newFieldRow('a', '2')] });
    expect(Object.values(dup)).toContain('Another field already has this name.');
    const many = Array.from({ length: 31 }, (_, i) => newFieldRow(`f${i}`, 'v'));
    expect(validateDraft({ ...d, custom: many }).fields).toMatch(/up to 30 fields/);
    expect(validateDraft({ ...d, fixed: { ...d.fixed, serial: 'x'.repeat(201) } }).serial).toMatch(/200 characters/);
  });
  it('puts server field errors under the right box', () => {
    const d = { ...draftFromRow(row({})), loc: 'gps' as const, custom: [newFieldRow('depot', 'x')] };
    const id = d.custom[0].id;
    expect(placeServerErrors({
      display_name: 'Too long.', 'tags[2]': 'Bad tag.', 'location.lon': 'Out of range.', location: 'Pick one kind.',
      'fields.vin': 'Too long.', 'fields.depot': 'Too long.', 'fields.ghost': 'Unknown.', weird: 'Something else.',
    }, d)).toEqual({
      display_name: 'Too long.', tags: 'Bad tag.', lon: 'Out of range.', lat: 'Pick one kind.', vin: 'Too long.',
      [`custom.${id}.value`]: 'Too long.', fields: 'Unknown.', form: 'Something else.',
    });
    expect(placeServerErrors(null, d)).toEqual({});
  });
});

describe('import and errors', () => {
  it('checks a CSV before sending it', () => {
    expect(csvPrecheck('  ')).toMatch(/Paste the CSV/);
    expect(csvPrecheck('name,type\nx,y')).toMatch(/header row/);
    expect(csvPrecheck('"group","node"')).toMatch(/no assets under it/);
    expect(csvPrecheck('﻿Group,Node,name\nfleet,t1,Truck')).toBeNull();
    expect(csvPrecheck('group,node\n' + Array.from({ length: 5001 }, (_, i) => `g,n${i}`).join('\n'))).toMatch(/up to 5000/);
    expect(csvPrecheck('group,node\ng,n', 3 * 1024 * 1024)).toMatch(/up to 2 MB/);
  });
  it('explains refusals in plain words', () => {
    expect(explainAssetError({ status: 403 }, 'save')).toMatch(/Manage telemetry/);
    expect(explainAssetError({ status: 404 }, 'load')).toMatch(/2.5.8/);
    expect(explainAssetError({ status: 404 }, 'delete')).toMatch(/no longer knows/);
    expect(explainAssetError({ status: 413 }, 'import')).toMatch(/2 MB/);
    expect(explainAssetError({ status: 0, code: 'NETWORK_ERROR' }, 'save')).toMatch(/Could not reach Abenix/);
    expect(explainAssetError({ status: 409, message: 'That asset was changed by someone else a moment ago.' }, 'save')).toBe('That asset was changed by someone else a moment ago.');
    expect(explainAssetError({ status: 500, message: 'Traceback (most recent call last)' }, 'import')).toMatch(/problem importing the list/);
  });
});
