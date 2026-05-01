'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Camera, Check, Loader2 } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { usePageTitle } from '@/hooks/usePageTitle';
import { apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';

export default function ProfilePage() {
  usePageTitle('Profile');
  const { user } = useAuth();
  const [fullName, setFullName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [changingPw, setChangingPw] = useState(false);
  const [profileMsg, setProfileMsg] = useState('');
  const [pwMsg, setPwMsg] = useState('');

  useEffect(() => {
    if (user) {
      setFullName(user.full_name || '');
      setAvatarUrl(user.avatar_url || '');
    }
  }, [user]);

  const handleSaveProfile = async () => {
    setSaving(true);
    setProfileMsg('');
    try {
      const res = await apiFetch('/api/settings/profile', {
        method: 'PUT',
        body: JSON.stringify({
          full_name: fullName,
          avatar_url: avatarUrl || null,
        }),
      });
      if (res.data) {
        setProfileMsg('Profile updated');
        toastSuccess('Profile updated');
        setTimeout(() => setProfileMsg(''), 3000);
      }
    } catch {
      setProfileMsg('Failed to update profile');
      toastError('Failed to update profile');
    } finally {
      setSaving(false);
    }
  };

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      setPwMsg('Passwords do not match');
      return;
    }
    if (newPassword.length < 8) {
      setPwMsg('Password must be at least 8 characters');
      return;
    }
    setChangingPw(true);
    setPwMsg('');
    try {
      const res = await apiFetch('/api/settings/password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (res.data) {
        setPwMsg('Password changed successfully');
        toastSuccess('Password changed');
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
        setTimeout(() => setPwMsg(''), 3000);
      } else {
        setPwMsg(res.error || 'Failed to change password');
        toastError('Failed to change password');
      }
    } catch {
      setPwMsg('Failed to change password');
      toastError('Failed to change password');
    } finally {
      setChangingPw(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <div>
        <h1 className="text-2xl font-bold text-white">Profile</h1>
        <p className="text-sm text-slate-500 mt-1">
          Manage your personal information
        </p>
      </div>

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 space-y-5">
        <div className="flex items-center gap-4">
          <div className="relative group">
            <div className="w-16 h-16 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-xl font-bold text-white">
              {fullName.charAt(0) || 'U'}
            </div>
            <div className="absolute inset-0 rounded-full bg-black/50 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity cursor-pointer">
              <Camera className="w-5 h-5 text-white" />
            </div>
          </div>
          <div>
            <p className="text-sm font-medium text-white">{user?.email}</p>
            <p className="text-xs text-slate-500 capitalize">
              {user?.role || 'member'}
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Full Name
            </label>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Email</label>
            <input
              type="email"
              value={user?.email || ''}
              disabled
              className="w-full px-3 py-2.5 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-slate-500 cursor-not-allowed"
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Avatar URL
            </label>
            <input
              type="text"
              value={avatarUrl}
              onChange={(e) => setAvatarUrl(e.target.value)}
              placeholder="https://..."
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-600 focus:border-cyan-500 focus:outline-none transition-colors"
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          {profileMsg && (
            <span className="text-xs text-emerald-400 flex items-center gap-1">
              <Check className="w-3 h-3" />
              {profileMsg}
            </span>
          )}
          <div className="ml-auto">
            <button
              onClick={handleSaveProfile}
              disabled={saving}
              className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all disabled:opacity-50 flex items-center gap-2"
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Save Changes
            </button>
          </div>
        </div>
      </div>

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-6 space-y-5">
        <h2 className="text-sm font-semibold text-white">Change Password</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Current Password
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none transition-colors"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              New Password
            </label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none transition-colors"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Confirm New Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="w-full px-3 py-2.5 bg-slate-800/50 border border-slate-700 rounded-lg text-sm text-slate-200 focus:border-cyan-500 focus:outline-none transition-colors"
            />
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          {pwMsg && (
            <span
              className={`text-xs ${
                pwMsg.includes('success') ? 'text-emerald-400' : 'text-red-400'
              }`}
            >
              {pwMsg}
            </span>
          )}
          <div className="ml-auto">
            <button
              onClick={handleChangePassword}
              disabled={changingPw || !currentPassword || !newPassword}
              className="px-4 py-2 text-sm font-medium text-slate-300 bg-slate-800/50 border border-slate-700/50 rounded-lg hover:text-white hover:border-slate-600/50 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {changingPw && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Update Password
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
