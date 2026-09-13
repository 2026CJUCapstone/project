import { useEffect, useState, useSyncExternalStore } from 'react';
import { Link } from 'react-router';
import { ArrowLeft, Settings } from 'lucide-react';
import { AuthModal } from '../components/AuthModal';
import { ProfileStatsPanel } from '../components/ProfileStatsPanel';
import { getCurrentUser } from '../services/authApi';
import { ApiError } from '../services/apiBase';
import { setAuthToken, subscribeAuthIdentity } from '../services/authIdentity';
import { profileFromAuthUser, saveLeaderboardProfile, type LeaderboardProfile } from '../services/leaderboardProfile';

const currentToken = () => localStorage.getItem('authToken');

export function Profile() {
  const token = useSyncExternalStore(subscribeAuthIdentity, currentToken, () => null);
  const [loginOpen, setLoginOpen] = useState(false);
  return (
    <section aria-labelledby="profile-heading" className="h-full w-full min-w-0 overflow-y-auto bg-gray-50 dark:bg-[#0d1117]">
      <div className="mx-auto w-full max-w-7xl space-y-6 px-4 py-6 sm:px-6 sm:py-10">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-blue-500 dark:text-gray-400"><ArrowLeft size={16} /> 홈으로</Link>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h1 id="profile-heading" className="text-2xl font-bold sm:text-3xl">내 프로필</h1>
          {token && <Link to="/settings" className="inline-flex items-center gap-2 rounded-md border border-gray-300 px-4 py-2 text-sm hover:bg-gray-100 dark:border-[#444] dark:hover:bg-[#252525]"><Settings size={16} /> 프로필 편집</Link>}
        </div>
        {token ? <ProfileOverview key={token} token={token} /> : (
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-[#333] dark:bg-[#151515]">
            <p className="mb-4 text-gray-600 dark:text-gray-300">로그인하면 내 프로필을 확인할 수 있습니다.</p>
            <button onClick={() => setLoginOpen(true)} className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">로그인하기</button>
          </div>
        )}
      </div>
      <AuthModal isOpen={!token && loginOpen} onClose={() => setLoginOpen(false)} onLogin={() => setLoginOpen(false)} />
    </section>
  );
}

function ProfileOverview({ token }: { token: string }) {
  const [user, setUser] = useState<LeaderboardProfile | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setError('');
    void getCurrentUser().then(value => {
      if (!active || currentToken() !== token) return;
      const profile = profileFromAuthUser(value);
      setUser(profile);
      saveLeaderboardProfile(profile);
    }).catch(reason => {
      if (!active || currentToken() !== token) return;
      if (reason instanceof ApiError && (reason.status === 401 || reason.status === 403)) setAuthToken(null);
      else setError('프로필을 불러오지 못했습니다. 다시 시도해 주세요.');
    });
    return () => { active = false; };
  }, [token, attempt]);

  if (error) return <div role="alert"><p>{error}</p><button onClick={() => setAttempt(value => value + 1)} className="mt-3 text-blue-500 underline">다시 시도</button></div>;
  if (!user) return <p role="status" className="text-gray-500 dark:text-gray-400">프로필을 불러오는 중...</p>;
  return <div className="min-w-0 space-y-6">
    <p className="break-all text-sm text-gray-500 dark:text-gray-400">{user.username ?? user.name} · {user.role === 'admin' ? '관리자' : '사용자'}</p>
    <ProfileStatsPanel user={user} />
  </div>;
}
