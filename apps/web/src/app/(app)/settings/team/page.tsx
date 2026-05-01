'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown,
  Loader2,
  Mail,
  MoreHorizontal,
  Plus,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';
import { apiFetch } from '@/lib/api-client';
import ConfirmModal from '@/components/ui/ConfirmModal';
import { toastSuccess, toastError } from '@/stores/toastStore';

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

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setInviteError('');
    try {
      const res = await apiFetch<Invite>('/api/team/invite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: inviteEmail.trim(), role: inviteRole }),
      });
      if (res.data) {
        setInviteEmail('');
        setShowInvite(false);
        mutateTeam();
        toastSuccess('Invitation sent');
      } else {
        setInviteError(res.error || 'Failed to invite');
        toastError('Failed to send invitation');
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
    try {
      await apiFetch(`/api/team/members/${memberId}/role`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role }),
      });
      mutateTeam();
      toastSuccess('Role updated');
    } catch {
      toastError('Failed to update role');
    }
  };

  const handleRemoveMember = (member: Member) => {
    setMenuOpen(null);
    setRemovingMember(member);
  };

  const confirmRemoveMember = async () => {
    if (!removingMember) return;
    setRemoveLoading(true);
    try {
      await apiFetch(`/api/team/members/${removingMember.id}`, { method: 'DELETE' });
      mutateTeam();
      toastSuccess('Member removed');
    } catch {
      toastError('Failed to remove member');
    } finally {
      setRemoveLoading(false);
      setRemovingMember(null);
    }
  };

  const handleCancelInvite = async (inviteId: string) => {
    try {
      await apiFetch(`/api/team/invites/${inviteId}`, { method: 'DELETE' });
      mutateTeam();
      toastSuccess('Invitation cancelled');
    } catch {
      toastError('Failed to cancel invitation');
    }
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Team</h1>
          <p className="text-sm text-slate-500 mt-1">
            Manage workspace members and permissions
          </p>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all"
        >
          <Plus className="w-4 h-4" />
          Invite Member
        </button>
      </div>

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
            <div className="flex items-center gap-3">
              <div className="flex-1 flex items-center gap-2">
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="email@example.com"
                  className="flex-1 px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none transition-colors"
                  onKeyDown={(e) => e.key === 'Enter' && handleInvite()}
                />
                <select
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

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
        {members
          .filter((m) => m.is_active)
          .map((member, i, arr) => (
            <div
              key={member.id}
              className={`flex items-center gap-4 p-4 ${
                i < arr.length - 1 || invites.length > 0
                  ? 'border-b border-slate-700/30'
                  : ''
              }`}
            >
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-sm font-bold text-white shrink-0">
                {member.full_name.charAt(0)}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-white">
                  {member.full_name}
                </p>
                <p className="text-xs text-slate-500">{member.email}</p>
              </div>
              <span
                className={`text-xs px-2 py-0.5 rounded-full capitalize ${
                  ROLE_COLORS[member.role] || ROLE_COLORS.user
                }`}
              >
                {member.role}
              </span>
              <div className="relative">
                <button
                  onClick={() =>
                    setMenuOpen(menuOpen === member.id ? null : member.id)
                  }
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
                <span className="text-xs text-cyan-400 bg-cyan-500/10 px-1.5 py-0.5 rounded">
                  Pending
                </span>
              </div>
              <p className="text-xs text-slate-600">
                Invited as {invite.role}
              </p>
            </div>
            <button
              onClick={() => handleCancelInvite(invite.id)}
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
