import { useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { AuthModal } from '../components/AuthModal';
import { saveLeaderboardProfile, type LeaderboardProfile } from '../services/leaderboardProfile';
import { requestPasswordReset } from '../services/authApi';

export function PasswordReset() {
  const location = useLocation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(true);
  const [identity, setIdentity] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const resetToken = useMemo(() => new URLSearchParams(location.search).get('resetToken'), [location.search]);

  const close = () => {
    setOpen(false);
    navigate('/', { replace: true });
  };

  const submitResetRequest = async (event: React.FormEvent) => {
    event.preventDefault();
    const normalizedIdentity = identity.trim();
    setError('');
    setNotice('');
    if (normalizedIdentity.length < 3) {
      setError('아이디 또는 이메일을 입력하세요.');
      return;
    }

    try {
      setIsSubmitting(true);
      const response = await requestPasswordReset(normalizedIdentity);
      setNotice(response.message);
      if (response.debugResetToken) {
        navigate(`/reset-password?resetToken=${encodeURIComponent(response.debugResetToken)}`, { replace: true });
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '재설정 요청에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!resetToken) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4 text-gray-900 dark:bg-[#121212] dark:text-white">
        <form onSubmit={submitResetRequest} className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 shadow-sm dark:border-[#333] dark:bg-[#1e1e1e]">
          <h1 className="text-2xl font-bold">비밀번호 찾기</h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">가입한 아이디 또는 이메일을 입력하면 비밀번호 재설정 안내를 받을 수 있습니다.</p>
          <label className="mt-6 block text-sm font-medium" htmlFor="reset-identity">아이디 또는 이메일</label>
          <input id="reset-identity" value={identity} onChange={(event) => setIdentity(event.target.value)} required className="mt-2 w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-gray-900 dark:border-[#333] dark:bg-[#141414] dark:text-white" placeholder="developer_123 또는 you@example.com" />
          {notice && <p className="mt-4 text-sm text-green-700 dark:text-green-400" role="status">{notice}</p>}
          {error && <p className="mt-4 text-sm text-red-600" role="alert">{error}</p>}
          <div className="mt-6 flex items-center justify-between gap-3">
            <button type="button" onClick={close} className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400">로그인으로 돌아가기</button>
            <button type="submit" disabled={isSubmitting} className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60">{isSubmitting ? '요청 중...' : '재설정 안내 받기'}</button>
          </div>
        </form>
      </main>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 text-gray-900 dark:bg-[#121212] dark:text-white">
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
