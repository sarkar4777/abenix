'use client';

import { motion } from 'framer-motion';
import { MoreHorizontal, Plus, Users, Loader2 } from 'lucide-react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useApi } from '@/hooks/useApi';

interface TeamMember {
  id: string;
  full_name: string;
  email: string;
  role: string;
  avatar_url?: string;
  is_active: boolean;
}

const roleColor: Record<string, string> = {
  admin: 'text-amber-400 bg-amber-500/10',
  creator: 'text-purple-400 bg-purple-500/10',
  user: 'text-slate-400 bg-slate-500/10',
};

export default function TeamPage() {
  usePageTitle('Team');
  const { data: members, isLoading } = useApi<TeamMember[]>('/api/team/members');

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-3xl"
    >
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Team</h1>
          <p className="text-sm text-slate-500 mt-1">Manage workspace members and permissions</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-500 to-blue-600 text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
          <Plus className="w-4 h-4" />
          Invite Member
        </button>
      </div>

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden overflow-x-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-slate-500">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading members...
          </div>
        ) : !members || members.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <Users className="w-8 h-8 mb-2 text-slate-700" />
            <p className="text-sm">No team members yet</p>
          </div>
        ) : (
          members.map((member, i) => (
            <div
              key={member.id}
              className={`flex items-center gap-4 p-4 ${i < members.length - 1 ? 'border-b border-slate-700/30' : ''}`}
            >
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-sm font-bold text-white shrink-0">
                {member.full_name?.charAt(0)?.toUpperCase() || '?'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-white">{member.full_name}</p>
                  {!member.is_active && (
                    <span className="text-xs text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">Inactive</span>
                  )}
                </div>
                <p className="text-xs text-slate-500">{member.email}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full ${roleColor[member.role] || 'text-slate-400 bg-slate-500/10'}`}>
                {member.role}
              </span>
              <button className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/50 transition-colors">
                <MoreHorizontal className="w-4 h-4" />
              </button>
            </div>
          ))
        )}
      </div>
    </motion.div>
  );
}
