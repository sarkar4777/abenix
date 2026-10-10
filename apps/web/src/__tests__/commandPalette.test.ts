vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api-client', () => ({ apiFetch: vi.fn(async () => ({ data: null, error: null })) }));
vi.mock('@/hooks/useApi', () => ({ useApi: () => ({ data: null, error: null, isLoading: false }) }));

import { commandsFor, decisionResults, isJunkLabel, matchCommands } from '@/components/ui/CommandPalette';

const hrefs = (q: string, perms?: Parameters<typeof commandsFor>[0]) => matchCommands(q, commandsFor(perms)).map((c) => c.href);
const ADMIN = { is_admin: true, capabilities: ['*'], features: { manage_team: true } };
const MEMBER = { is_admin: false, capabilities: ['decisions.view', 'decisions.evaluate', 'risk.view'], features: { manage_team: false } };

describe('command palette pages', () => {
  it('finds Decisions by its name or by "rules"', () => {
    expect(hrefs('decision')).toContain('/decisions');
    expect(hrefs('rules')).toContain('/decisions');
    expect(hrefs('business rule')).toContain('/decisions');
  });

  it('maps plain words about approving to Team and Approvals', () => {
    for (const q of ['approve', 'approver', 'sign off', 'who can approve']) {
      expect(hrefs(q, ADMIN), q).toEqual(expect.arrayContaining(['/settings/team', '/approvals']));
    }
    expect(hrefs('who can approve', ADMIN)).toContain('/admin/permissions');
    expect(hrefs('invite', ADMIN)).toContain('/settings/team');
  });

  it('gives a member Team as view only and leaves out what they cannot open', () => {
    const forMember = matchCommands('who can approve', commandsFor(MEMBER));
    expect(forMember.map((c) => c.href)).toEqual(expect.arrayContaining(['/settings/team', '/approvals']));
    expect(forMember.find((c) => c.href === '/settings/team')?.label).toBe('Team (view only)');
    expect(forMember.map((c) => c.href)).not.toContain('/admin/permissions');
    expect(matchCommands('team', commandsFor(ADMIN)).find((c) => c.href === '/settings/team')?.label).toBe('Team');
  });
});

describe('command palette decisions', () => {
  const rows = [
    { key: 'gw.safety.exclusion', name: 'Machine stop near worker', description: 'Whether a slewing machine must stop' },
    { key: 'sample_plant_limits', name: 'Sample plant limits', description: 'Setpoint limits for the plant' },
  ];

  it('finds a decision by its name, its key or its description', () => {
    expect(decisionResults(rows, 'machine stop').map((r) => r.href)).toEqual(['/decisions/gw.safety.exclusion']);
    expect(decisionResults(rows, 'sample_plant').map((r) => r.label)).toEqual(['Sample plant limits']);
    expect(decisionResults(rows, 'slewing').map((r) => r.subtitle)).toEqual(['gw.safety.exclusion']);
    expect(decisionResults(rows, 'nothing like this')).toEqual([]);
  });

  it('drops run logs that are mostly symbols', () => {
    expect(isJunkLabel('ContractIQ Document Extractor: ================')).toBe(true);
    expect(isJunkLabel('Machine stop near worker')).toBe(false);
  });
});
