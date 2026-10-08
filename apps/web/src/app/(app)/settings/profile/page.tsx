'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Camera, Check, Loader2, Trash2, User } from 'lucide-react';
import PageHeader from '@/components/layout/PageHeader';
import { useAuth } from '@/contexts/AuthContext';
import { usePageTitle } from '@/hooks/usePageTitle';
import { API_URL, ApiError, apiFetch } from '@/lib/api-client';
import { toastSuccess, toastError } from '@/stores/toastStore';

interface Profile {
  full_name: string;
  avatar_url: string | null;
}

const MAX_AVATAR_BYTES = 2 * 1024 * 1024;
const AVATAR_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];

// uploaded pictures are stored as API paths, links typed by the user are full URLs
function avatarSrc(url: string): string {
  return url.startsWith('/api/') ? `${API_URL}${url}` : url;
}

function avatarUrlProblem(raw: string): string | null {
  const value = raw.trim();
  if (!value || value.startsWith('/api/settings/avatars/')) return null;
  if (/[\s<>"'`]/.test(value)) return 'A picture link cannot contain spaces or < > " \' characters.';
  try {
    const u = new URL(value);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return 'Enter a full picture link that starts with https://';
  } catch {
    return 'Enter a full picture link that starts with https://';
  }
  if (value.length > 500) return 'The picture link is too long. Use one under 500 characters.';
  return null;
}

function errMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError || e instanceof Error) return e.message || fallback;
  return fallback;
}

export default function ProfilePage() {
  usePageTitle('Profile');
  const { user, updateUser } = useAuth();
  const [fullName, setFullName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [previewBroken, setPreviewBroken] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [changingPw, setChangingPw] = useState(false);
  const [profileMsg, setProfileMsg] = useState('');
  const [nameErr, setNameErr] = useState<string | null>(null);
  const [avatarErr, setAvatarErr] = useState<string | null>(null);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (user) {
      setFullName(user.full_name || '');
      setAvatarUrl(user.avatar_url || '');
    }
  }, [user]);

  useEffect(() => {
    setPreviewBroken(false);
  }, [avatarUrl]);

  const urlProblem = avatarUrlProblem(avatarUrl);
  const shownAvatar = avatarUrl.trim() && !urlProblem && !previewBroken ? avatarSrc(avatarUrl.trim()) : null;

  const applySaved = (p: Profile, msg: string) => {
    updateUser({ full_name: p.full_name, avatar_url: p.avatar_url });
    setFullName(p.full_name || '');
    setAvatarUrl(p.avatar_url || '');
    setProfileMsg(msg);
    toastSuccess(msg);
    setTimeout(() => setProfileMsg(''), 3000);
  };

  const handleSaveProfile = async () => {
    setProfileMsg('');
    const name = fullName.trim();
    const nErr = name ? null : 'Enter your name.';
    const aErr = urlProblem || (previewBroken ? 'That link did not load as a picture. Check it or clear the field.' : null);
    setNameErr(nErr);
    setAvatarErr(aErr);
    if (nErr || aErr) return;
    setSaving(true);
    try {
      const res = await apiFetch<Profile>('/api/settings/profile', {
        method: 'PUT',
        body: JSON.stringify({ full_name: name, avatar_url: avatarUrl.trim() || null }),
      });
      if (res.data) applySaved(res.data, 'Profile updated');
    } catch (e) {
      const msg = errMessage(e, 'Could not save your profile. Try again.');
      const field = e instanceof ApiError ? e.details?.field : undefined;
      if (field === 'avatar_url') setAvatarErr(msg);
      else if (field === 'full_name') setNameErr(msg);
      else toastError(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file) return;
    setAvatarErr(null);
    if (!AVATAR_TYPES.includes(file.type)) {
      setAvatarErr('Pick a PNG, JPEG, GIF or WebP picture.');
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarErr('That picture is larger than 2 MB. Pick a smaller one.');
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await apiFetch<Profile>('/api/settings/avatar', { method: 'POST', body: form });
      if (res.data) applySaved(res.data, 'Picture updated');
    } catch (e) {
      setAvatarErr(errMessage(e, 'Could not upload the picture. Try again.'));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const handleRemoveAvatar = async () => {
    setAvatarErr(null);
    setSaving(true);
    try {
      const res = await apiFetch<Profile>('/api/settings/profile', {
        method: 'PUT',
        body: JSON.stringify({ avatar_url: null }),
      });
      if (res.data) applySaved(res.data, 'Picture removed');
    } catch (e) {
      setAvatarErr(errMessage(e, 'Could not remove the picture. Try again.'));
    } finally {
      setSaving(false);
    }
  };

  const handleChangePassword = async () => {
    if (newPassword !== confirmPassword) {
      setPwMsg({ ok: false, text: 'The new passwords do not match.' });
      return;
    }
    if (newPassword.length < 8) {
      setPwMsg({ ok: false, text: 'Use at least 8 characters for the new password.' });
      return;
    }
    setChangingPw(true);
    setPwMsg(null);
    try {
      const res = await apiFetch('/api/settings/password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (res.data) {
        setPwMsg({ ok: true, text: 'Password changed. Use the new one next time you sign in.' });
        toastSuccess('Password changed');
        setCurrentPassword('');
        setNewPassword('');
        setConfirmPassword('');
        setTimeout(() => setPwMsg(null), 4000);
      }
    } catch (e) {
      const msg = errMessage(e, 'Could not change the password. Try again.');
      setPwMsg({ ok: false, text: msg });
      toastError(msg);
    } finally {
      setChangingPw(false);
    }
  };

  const inputCls = (bad: boolean) =>
    `w-full px-3 py-2.5 bg-slate-800/50 border rounded-lg text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none transition-colors ${
      bad ? 'border-rose-500/70 focus:border-rose-400' : 'border-slate-700 focus:border-cyan-500'
    }`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="space-y-6 max-w-2xl"
    >
      <PageHeader
        title="Profile"
        icon={User}
        purpose="Your name and picture as teammates see them, and the password you sign in with. For everyone."
        primaryAction={{
          label: uploading ? 'Uploading...' : 'Upload picture',
          icon: uploading ? Loader2 : Camera,
          busy: uploading,
          onClick: () => fileRef.current?.click(),
        }}
        steps={[
          'Upload a picture or paste a link to one. Leave it empty to show your initial.',
          'Change your name and press Save changes.',
          'Change your password below. Other signed in sessions stay signed in.',
        ]}
        storageKey="settings-profile"
      />

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6 space-y-5">
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            aria-label="Upload a new picture"
            title="Upload a new picture"
            className="relative group w-16 h-16 rounded-full shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
            data-testid="avatar-upload-trigger"
          >
            {shownAvatar ? (
              <img
                src={shownAvatar}
                alt=""
                onError={() => setPreviewBroken(true)}
                className="w-16 h-16 rounded-full object-cover"
                data-testid="avatar-preview"
              />
            ) : (
              <span className="w-16 h-16 rounded-full bg-gradient-to-br from-cyan-500 to-purple-600 flex items-center justify-center text-xl font-bold text-white">
                {fullName.trim().charAt(0).toUpperCase() || 'U'}
              </span>
            )}
            <span className="absolute inset-0 rounded-full bg-black/50 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 flex items-center justify-center transition-opacity">
              {uploading ? <Loader2 className="w-5 h-5 text-white animate-spin" /> : <Camera className="w-5 h-5 text-white" />}
            </span>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={AVATAR_TYPES.join(',')}
            className="hidden"
            onChange={(e) => handleUpload(e.target.files?.[0])}
            data-testid="avatar-file"
          />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-white break-all">{user?.email}</p>
            <p className="text-xs text-slate-500 capitalize">{user?.role || 'member'}</p>
            <div className="flex flex-wrap gap-3 mt-1">
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                className="text-xs text-cyan-300 hover:text-cyan-200 disabled:opacity-50"
              >
                Upload picture
              </button>
              {user?.avatar_url && (
                <button
                  type="button"
                  onClick={handleRemoveAvatar}
                  disabled={saving}
                  className="inline-flex items-center gap-1 text-xs text-slate-400 hover:text-rose-300 disabled:opacity-50"
                  data-testid="avatar-remove"
                >
                  <Trash2 className="w-3 h-3" /> Remove picture
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">PNG, JPEG, GIF or WebP, up to 2 MB.</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label htmlFor="profile-name" className="block text-xs text-slate-400 mb-1.5">
              Full name
            </label>
            <input
              id="profile-name"
              type="text"
              value={fullName}
              maxLength={255}
              onChange={(e) => {
                setFullName(e.target.value);
                setNameErr(null);
              }}
              aria-invalid={!!nameErr}
              aria-describedby={nameErr ? 'profile-name-err' : undefined}
              className={inputCls(!!nameErr)}
            />
            {nameErr && (
              <p id="profile-name-err" className="text-xs text-rose-300 mt-1" role="alert">
                {nameErr}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="profile-email" className="block text-xs text-slate-400 mb-1.5">
              Email
            </label>
            <input
              id="profile-email"
              type="email"
              value={user?.email || ''}
              disabled
              aria-describedby="profile-email-help"
              className="w-full px-3 py-2.5 bg-slate-900/50 border border-slate-700/50 rounded-lg text-sm text-slate-500 cursor-not-allowed"
            />
            <p id="profile-email-help" className="text-[11px] text-slate-500 mt-1">
              Your sign-in email cannot be changed here.
            </p>
          </div>

          <div>
            <label htmlFor="profile-avatar" className="block text-xs text-slate-400 mb-1.5">
              Picture link <span className="text-slate-600">(optional, or upload one above)</span>
            </label>
            <input
              id="profile-avatar"
              type="url"
              value={avatarUrl}
              onChange={(e) => {
                setAvatarUrl(e.target.value);
                setAvatarErr(null);
              }}
              placeholder="https://example.com/me.png"
              aria-invalid={!!(avatarErr || (avatarUrl.trim() && urlProblem))}
              aria-describedby="profile-avatar-help"
              className={inputCls(!!(avatarErr || (avatarUrl.trim() && urlProblem)))}
              data-testid="avatar-url"
            />
            <p
              id="profile-avatar-help"
              role={avatarErr || urlProblem || previewBroken ? 'alert' : undefined}
              className={`text-[11px] mt-1 ${avatarErr || urlProblem || previewBroken ? 'text-rose-300' : 'text-slate-500'}`}
            >
              {avatarErr ||
                urlProblem ||
                (previewBroken
                  ? 'That link did not load as a picture. Check it or clear the field.'
                  : 'Clear the field and save to go back to your initial.')}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          {profileMsg && (
            <span className="text-xs text-emerald-400 flex items-center gap-1" role="status">
              <Check className="w-3 h-3" />
              {profileMsg}
            </span>
          )}
          <div className="ml-auto">
            <button
              onClick={handleSaveProfile}
              disabled={saving || uploading}
              className="px-4 py-2 bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-medium rounded-lg hover:from-cyan-400 hover:to-purple-500 shadow-lg shadow-cyan-500/25 transition-all disabled:opacity-50 flex items-center gap-2"
              data-testid="profile-save"
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Save changes
            </button>
          </div>
        </div>
      </div>

      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl p-4 sm:p-6 space-y-5">
        <div>
          <h2 className="text-sm font-semibold text-white">Change password</h2>
          <p className="text-xs text-slate-500 mt-1">
            Takes effect at once. Sessions already signed in stay signed in.
          </p>
        </div>

        <div className="space-y-4">
          <div>
            <label htmlFor="pw-current" className="block text-xs text-slate-400 mb-1.5">
              Current password
            </label>
            <input
              id="pw-current"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className={inputCls(false)}
            />
          </div>
          <div>
            <label htmlFor="pw-new" className="block text-xs text-slate-400 mb-1.5">
              New password <span className="text-slate-600">(at least 8 characters)</span>
            </label>
            <input
              id="pw-new"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className={inputCls(false)}
            />
          </div>
          <div>
            <label htmlFor="pw-confirm" className="block text-xs text-slate-400 mb-1.5">
              Confirm new password
            </label>
            <input
              id="pw-confirm"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              aria-invalid={!!confirmPassword && confirmPassword !== newPassword}
              className={inputCls(!!confirmPassword && confirmPassword !== newPassword)}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          {pwMsg && (
            <span
              role={pwMsg.ok ? 'status' : 'alert'}
              data-testid="pw-message"
              className={`text-xs flex items-center gap-1 ${pwMsg.ok ? 'text-emerald-400' : 'text-rose-300'}`}
            >
              {pwMsg.ok ? <Check className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
              {pwMsg.text}
            </span>
          )}
          <div className="ml-auto">
            <button
              onClick={handleChangePassword}
              disabled={changingPw || !currentPassword || !newPassword || !confirmPassword}
              className="px-4 py-2 text-sm font-medium text-slate-300 bg-slate-800/50 border border-slate-700/50 rounded-lg hover:text-white hover:border-slate-600/50 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {changingPw && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Update password
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
