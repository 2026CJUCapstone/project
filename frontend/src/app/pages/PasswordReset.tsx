import { useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { AuthModal } from '../components/AuthModal';
import { saveLeaderboardProfile, type LeaderboardProfile } from '../services/leaderboardProfile';

export function PasswordReset() {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(true);
  const resetToken = useMemo(() => new URLSearchParams(location.search).get('resetToken'), [location.search]);

  const close = () => {
    setOpen(false);
    navigate('/', { replace: true });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 text-gray-900 dark:bg-[#121212] dark:text-white">
      <div className="rounded-md border border-gray-200 bg-white px-6 py-5 text-sm text-gray-600 shadow-sm dark:border-[#333] dark:bg-[#1e1e1e] dark:text-gray-300">
        비밀번호 재설정을 준비 중입니다.
      </div>
      <AuthModal
        isOpen={open}
        onClose={close}
        initialResetToken={resetToken}
        onLogin={(profile: LeaderboardProfile) => {
          saveLeaderboardProfile(profile);
          close();
        }}
      />
    </div>
  );
}
