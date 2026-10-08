'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot,
  Check,
  ChevronDown,
  Copy,
  Loader2,
  Mail,
  MoreHorizontal,
  Plus,
  Trash2,
  UserCog,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toastSuccess, toastError } from '@/stores/toastStore';
import { roleLabel } from '@/lib/monitor-format';

interface Member {
  id: string;
  email: string;
  full_name: string;
  avatar_url: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

interface Invite {
  id: string;
  email: string;
  role: string;
  status: string;
  created_at: string;
  expires_at: string;
  expired?: boolean;
  invite_url?: string;
}

const ROLE_COLORS: Record<string, string> = {
  admin: 'text-purple-400 bg-purple-500/10',
  creator: 'text-cyan-400 bg-cyan-500/10',
  user: 'text-slate-400 bg-slate-500/10',
};

interface TeamData {
  members: Member[];
  pending_invites: Invite[];
}

const ROLES = [
  { value: 'admin', label: 'Admin' },
  { value: 'creator', label: 'Creator' },
  { value: 'user', label: 'Member' },
];

export default function TeamPage() {
  usePageTitle('Team Settings');
  const {
    data: teamData,
    isLoading: loading,
    mutate: mutateTeam,
  } = useApi<TeamData>('/api/team/members');
  const members = teamData?.members ?? [];
  const invites = teamData?.pending_invites ?? [];
  const [showInvite, setShowInvite] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('user');
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState('');
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [removingMember, setRemovingMember] = useState<Member | null>(null);
  const [removeLoading, setRemoveLoading] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [showNext, setShowNext] = useState(false);

  const copyLink = async (url: string, key: string) => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(key);
      setTimeout(() => setCopied(null), 2000);
    } catch {
      toastError('Copy failed', 'Select the link and copy it by hand');
    }
  };

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setInviteError('');
    try {
      const res = await apiFetch<Invite>('/api/team/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
        throwOnError: false,
      });
      if (res.data) {
        setInviteEmail('');
        setShowInvite(false);
        setInviteLink(res.data.invite_url || null);
        setShowNext(true);
        mutateTeam();
        toastSuccess('Invite created', 'Copy the link and send it to your teammate');
      } else {
        setInviteError(res.error || 'Failed to invite');
        toastError('Failed to create invitation', res.error || undefined);
      }
    } catch {
      setInviteError('Failed to invite');
      toastError('Failed to send invitation');
    } finally {
      setInviting(false);
    }
  };

  const handleChangeRole = async (memberId: string, role: string) => {
    setMenuOpen(null);
    const res = await apiFetch(`/api/team/members/${memberId}/role`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
      throwOnError: false,
    });
    if (res.error) {
      toastError('Could not change the role', res.error);
      return;
    }
    mutateTeam();
    toastSuccess(`Role changed to ${roleLabel(role)}`);
  };

  const handleRemoveMember = (member: Member) => {
    setMenuOpen(null);
    setRemovingMember(member);
  };

  const confirmRemoveMember = async () => {
    if (!removingMember) return;
    setRemoveLoading(true);
    const res = await apiFetch(`/api/team/members/${removingMember.id}`, { method: 'DELETE', throwOnError: false });
    if (res.error) toastError('Could not remove this person', res.error);
    else {
      mutateTeam();
      toastSuccess('Member removed');
    }
    setRemoveLoading(false);
    setRemovingMember(null);
  };

  const handleCancelInvite = async (inviteId: string) => {
    const res = await apiFetch(`/api/team/invites/${inviteId}`, { method: 'DELETE', throwOnError: false });
    if (res.error) {
      toastError('Could not cancel the invitation', res.error);
      return;
    }
    mutateTeam();
    toastSuccess('Invitation cancelled');
  };

  if (loading) {
    return (
      <div className="space-y-6 max-w-2xl">
        <div className="flex items-center justify-between">
          <div>
            <div className="h-7 w-20 bg-slate-800 animate-pulse rounded" />
            <div className="h-3 w-52 bg-slate-700/50 animate-pulse rounded mt-2" />
          </div>
          <div className="h-9 w-36 bg-slate-800 animate-pulse rounded-lg" />
        </div>
        <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={`flex items-center gap-4 p-4 ${i < 3 ? 'border-b border-slate-700/30' : ''}`}>
              <div className="w-10 h-10 rounded-full bg-slate-800 animate-pulse shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-28 bg-slate-800 animate-pulse rounded" />
                <div className="h-3 w-40 bg-slate-700/50 animate-pulse rounded" />
              </div>
              <div className="h-5 w-14 bg-slate-800 animate-pulse rounded-full" />
              <div className="w-8 h-8 rounded-lg bg-slate-800 animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <PageHeader
        title="Team"
        icon={Users}
        purpose="Who is in this workspace, the role each person has, and invitations still waiting to be accepted. For workspace admins."
        primaryAction={{ label: 'Invite Member', icon: Plus, onClick: () => setShowInvite(true) }}
        steps={[
          'Invite someone by email and pick their role.',
          'Copy the invite link and send it to them. It works once and expires in 7 days.',
          'Admins manage everything, creators build agents, members use what is shared with them.',
          'Use the menu on a person to change their role or remove them.',
        ]}
        docSlug="01-architecture/01-tenants-rbac"
        storageKey="settings-team"
      />

      <AnimatePresence>
        {showInvite && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4"
          >
            <p className="text-sm text-white font-medium mb-3">
              Invite a team member
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex-1 min-w-[240px] flex items-center gap-2">
                <input
                  type="email"
                  aria-label="Email to invite"
                  data-testid="invite-email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="email@example.com"
                  className="flex-1 min-w-0 px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none transition-colors"
                  onKeyDown={(e) => e.key === 'Enter' && handleInvite()}
                />
                <select
                  aria-label="Role"
                  data-testid="invite-role"
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none"
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={handleInvite}
                data-testid="invite-send"
                disabled={inviting || !inviteEmail.trim()}
                className="px-4 py-2.5 bg-cyan-500/20 text-cyan-400 text-sm font-medium rounded-lg hover:bg-cyan-500/30 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {inviting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Send
              </button>
              <button
                onClick={() => {
                  setShowInvite(false);
                  setInviteEmail('');
                  setInviteError('');
                }}
                className="px-3 py-2.5 text-sm text-slate-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
            </div>
            {inviteError && (
              <p className="text-xs text-red-400 mt-2">{inviteError}</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {inviteLink && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-4">
          <div className="flex items-start justify-between mb-2">
            <p className="text-sm text-emerald-400 font-medium">
              Invite link ready. It works once and expires in 7 days.
            </p>
            <button
              onClick={() => setInviteLink(null)}
              aria-label="Dismiss invite link"
              className="text-slate-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex items-center gap-2">
            <code data-testid="invite-link" className="flex-1 px-3 py-2 bg-slate-900/50 rounded-lg text-xs text-emerald-300 font-mono break-all">
              {inviteLink}
            </code>
            <button
              onClick={() => copyLink(inviteLink, 'new')}
              data-testid="invite-link-copy"
              className="shrink-0 px-3 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg text-xs text-slate-300 hover:text-white transition-colors flex items-center gap-1.5"
            >
              {copied === 'new' ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              {copied === 'new' ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}

      {showNext && (
        <NextSteps
          title="Invite created. What next?"
          testId="invite-next-steps"
          onDismiss={() => setShowNext(false)}
          steps={[
            { id: 'invite-another', label: 'Invite someone else', hint: 'Add the next teammate while you are here.', icon: UserPlus, onClick: () => setShowInvite(true) },
            { id: 'permissions', label: 'Give extra abilities', hint: 'Add a permission set without making them an admin.', icon: UserCog, href: '/admin/permissions' },
            { id: 'share-agent', label: 'Share an agent', hint: 'Pick an agent and share it so they can use it.', icon: Bot, href: '/agents' },
          ]}
        />
      )}

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
        {members
          .filter((m) => m.is_active)
          .map((member, i, arr) => (
            <div
              key={member.id}
              data-testid={`member-${member.email}`}
              className={`flex items-center gap-3 sm:gap-4 p-4 ${
                i < arr.length - 1 || invites.length > 0
                  ? 'border-b border-slate-700/30'
                  : ''
              }`}
            >
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-sm font-bold text-white shrink-0">
                {member.full_name.charAt(0)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white truncate">
                  {member.full_name}
                </p>
                <p className="text-xs text-slate-500 truncate">{member.email}</p>
              </div>
              <span
                className={`text-xs px-2 py-0.5 rounded-full shrink-0 ${
                  ROLE_COLORS[member.role] || ROLE_COLORS.user
                }`}
                data-testid="member-role"
              >
                {roleLabel(member.role)}
              </span>
              <div className="relative">
                <button
                  onClick={() =>
                    setMenuOpen(menuOpen === member.id ? null : member.id)
                  }
                  aria-label={`Actions for ${member.email}`}
                  className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors"
                >
                  <MoreHorizontal className="w-4 h-4" />
                </button>
                {menuOpen === member.id && (
                  <div className="absolute right-0 top-full mt-1 w-40 bg-slate-800 border border-slate-700/50 rounded-lg shadow-xl z-10 py-1">
                    {ROLES.filter((r) => r.value !== member.role).map((r) => (
                      <button
                        key={r.value}
                        onClick={() => handleChangeRole(member.id, r.value)}
                        className="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-slate-700/50 hover:text-white transition-colors"
                      >
                        Set as {r.label}
                      </button>
                    ))}
                    <button
                      onClick={() => handleRemoveMember(member)}
                      className="w-full text-left px-3 py-2 text-xs text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                      Remove member
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}

        {invites.map((invite, i) => (
          <div
            key={invite.id}
            data-testid={`invite-${invite.email}`}
            className={`flex items-center gap-4 p-4 ${
              i < invites.length - 1 ? 'border-b border-slate-700/30' : ''
            }`}
          >
            <div className="w-10 h-10 rounded-full bg-slate-700/50 flex items-center justify-center text-sm text-slate-400 shrink-0">
              <Mail className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <p className="text-sm text-slate-400">{invite.email}</p>
                {invite.expired ? (
                  <span className="text-xs text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
                    Expired
                  </span>
                ) : (
                  <span className="text-xs text-cyan-400 bg-cyan-500/10 px-1.5 py-0.5 rounded">
                    Pending
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-600">
                Invited as {roleLabel(invite.role)}
              </p>
            </div>
            {invite.invite_url && !invite.expired && (
              <button
                onClick={() => copyLink(invite.invite_url!, invite.id)}
                data-testid={`invite-copy-${invite.id}`}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs text-slate-300 bg-slate-700/40 hover:bg-slate-700 rounded-lg transition-colors"
              >
                {copied === invite.id ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                {copied === invite.id ? 'Copied' : 'Copy link'}
              </button>
            )}
            <button
              onClick={() => handleCancelInvite(invite.id)}
              aria-label={`Cancel invite for ${invite.email}`}
              className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      <ConfirmModal
        open={!!removingMember}
        onClose={() => setRemovingMember(null)}
        onConfirm={confirmRemoveMember}
        title="Remove team member"
        description={`Are you sure you want to remove ${removingMember?.full_name || 'this member'}? They will lose access to the workspace immediately.`}
        confirmLabel="Remove"
        variant="danger"
        loading={removeLoading}
      />
    </motion.div>
  );
}
