import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Gauge } from 'lucide-react';

const permsState: { perms: Record<string, unknown> | undefined; loading: boolean } = { perms: undefined, loading: false };

vi.mock('@/lib/capabilities', async (orig) => {
  const actual = await orig<typeof import('@/lib/capabilities')>();
  return { ...actual, useMyPermissions: () => permsState };
});

import NoAccess, { AccessGate, canAccess } from '@/components/layout/NoAccess';

const member = { role: 'user', is_admin: false, features: { manage_settings: false }, capabilities: ['agents.view'] };
const admin = { role: 'admin', is_admin: true, features: { manage_settings: true }, capabilities: ['*'] };

describe('canAccess', () => {
  it('checks the admin role, a feature flag and a capability', () => {
    expect(canAccess(member, { admin: true })).toBe(false);
    expect(canAccess(admin, { admin: true })).toBe(true);
    expect(canAccess(member, { feature: 'manage_settings' })).toBe(false);
    expect(canAccess({ ...member, features: { manage_settings: true } }, { feature: 'manage_settings' })).toBe(true);
    expect(canAccess(member, { capability: 'events.manage', label: 'Manage events' })).toBe(false);
    expect(canAccess({ ...member, capabilities: ['events.*'] }, { capability: 'events.manage', label: 'Manage events' })).toBe(true);
    expect(canAccess(undefined, { admin: true })).toBe(false);
  });
});

describe('NoAccess', () => {
  it('keeps the page title and purpose and says who can use it', () => {
    render(<NoAccess title="Scaling Console" purpose="Choose where each agent runs. For admins." icon={Gauge} need={{ admin: true }} role="creator" />);
    expect(screen.getByTestId('page-header')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Scaling Console');
    expect(screen.getByTestId('page-purpose')).toHaveTextContent('Choose where each agent runs.');
    expect(screen.getByTestId('no-access-who')).toHaveTextContent('Only admins can use Scaling Console');
    expect(screen.getByTestId('no-access-who')).toHaveTextContent('signed in as a Creator');
  });

  it('names the capability in a code reference after the plain label', () => {
    render(<NoAccess title="Events" purpose="Call your own system when something happens." need={{ capability: 'events.manage', label: 'Manage events' }} />);
    const who = screen.getByTestId('no-access-who');
    expect(who).toHaveTextContent('needs the Manage events permission');
    expect(who.querySelector('code')).toHaveTextContent('events.manage');
  });

  it('makes asking an admin the primary action and links onward', () => {
    render(
      <NoAccess
        title="LLM Pricing"
        purpose="Set what each model costs."
        need={{ feature: 'manage_settings' }}
        instead={{ text: 'Your spend is on Analytics.', href: '/analytics', label: 'Open Analytics' }}
      />,
    );
    const primary = screen.getByTestId('page-primary-action');
    expect(primary.querySelector('a')).toHaveAttribute('href', '/settings/team');
    expect(primary).toHaveTextContent('Ask an admin');
    expect(screen.getByTestId('no-access-instead')).toHaveAttribute('href', '/analytics');
  });

  it('defaults the onward link to the dashboard', () => {
    render(<NoAccess title="Roles" purpose="Who has which role." need={{ admin: true }} />);
    expect(screen.getByTestId('no-access-instead')).toHaveAttribute('href', '/dashboard');
  });
});

describe('AccessGate', () => {
  beforeEach(() => {
    permsState.perms = undefined;
    permsState.loading = false;
  });

  const gate = () =>
    render(
      <AccessGate title="Tool Configuration" purpose="Keys that built in tools need." need={{ feature: 'manage_settings' }}>
        <p>secret page</p>
      </AccessGate>,
    );

  it('shows NoAccess instead of the page for a member', () => {
    permsState.perms = member;
    gate();
    expect(screen.queryByText('secret page')).toBeNull();
    expect(screen.getByTestId('no-access')).toHaveTextContent('Only admins can use Tool Configuration');
  });

  it('shows the page for an admin', () => {
    permsState.perms = admin;
    gate();
    expect(screen.getByText('secret page')).toBeInTheDocument();
    expect(screen.queryByTestId('no-access')).toBeNull();
  });

  it('waits while permissions load, never flashing either', () => {
    permsState.loading = true;
    gate();
    expect(screen.queryByText('secret page')).toBeNull();
    expect(screen.queryByTestId('no-access')).toBeNull();
  });
});
