import { alertNames, filterAlerts, firingStepLink, resolvesText } from '@/lib/alertsFilter';

const A = [
  { name: 'TelemetryDeviceOffline', state: 'firing', summary: 'Part SHP1 of DSV went offline', labels: { group: 'DSV', node: 'SHP1' } },
  { name: 'TelemetryDeviceOffline', state: 'silenced', summary: 'Part SHP2 of DB Schenker went offline', labels: { group: 'DB Schenker', node: 'SHP2' } },
  { name: 'TelemetryRule', state: 'firing', summary: 'Oil hot on EX1', labels: { rule_id: 'r1', rule: 'Oil hot' } },
];

describe('platform alert filters (gap 3)', () => {
  it('filters by rule, name, status, label and text', () => {
    expect(filterAlerts(A, { rule: 'r1' }).map((a) => a.name)).toEqual(['TelemetryRule']);
    expect(filterAlerts(A, { alertname: 'TelemetryDeviceOffline' })).toHaveLength(2);
    expect(filterAlerts(A, { status: 'muted' })).toHaveLength(1);
    expect(filterAlerts(A, { q: 'group=dsv' }).map((a) => a.labels.node)).toEqual(['SHP1']);
    expect(filterAlerts(A, { q: 'schenker' })).toHaveLength(1);
    expect(filterAlerts(A, {})).toHaveLength(3);
  });
  it('counts alert names, most first', () => {
    expect(alertNames(A)[0]).toEqual({ name: 'TelemetryDeviceOffline', count: 2 });
  });
  it('never says resolves just now on an alert still firing', () => {
    const soon = new Date(Date.now() + 4 * 60_000).toISOString();
    expect(resolvesText('firing', soon)).toBeNull();
    expect(resolvesText('inactive', new Date(Date.now() - 5 * 60_000).toISOString())).toBe('resolved 5m ago');
  });
  it('opens the alert filtered to the rule that raised it', () => {
    expect(firingStepLink('/alerts', 'r1', 'TelemetryRule')).toBe('/alerts?rule=r1&alertname=TelemetryRule');
    expect(firingStepLink('/executions/e1', 'r1')).toBe('/executions/e1');
  });
});
