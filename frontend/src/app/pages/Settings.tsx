import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from 'react';
import { Link } from 'react-router';
import { ArrowLeft } from 'lucide-react';
import { AuthModal } from '../components/AuthModal';
import { getCurrentUser, updateProfile } from '../services/authApi';
import { ApiError } from '../services/apiBase';
import { setAuthToken, subscribeAuthIdentity } from '../services/authIdentity';
import { profileFromAuthUser, saveLeaderboardProfile, type LeaderboardProfile } from '../services/leaderboardProfile';
import { useCompilerStore } from '../store/compilerStore';

const currentToken = () => localStorage.getItem('authToken');

export function Settings() {
  const token = useSyncExternalStore(subscribeAuthIdentity, currentToken, () => null);
  const [loginOpen, setLoginOpen] = useState(false);
  return (
    <section aria-labelledby="settings-heading" className="h-full w-full min-w-0 overflow-y-auto bg-gray-50 dark:bg-[#0d1117]">
      <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6 sm:py-10">
        <Link to="/profile" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-blue-500 dark:text-gray-400">
          <ArrowLeft size={16} /> 내 프로필로
        </Link>
        <h1 id="settings-heading" className="text-2xl font-bold text-gray-900 dark:text-white sm:text-3xl">설정</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400">프로필 정보와 에디터·화면 설정을 관리합니다.</p>
        {token ? <ProfileEditor key={token} token={token} /> : (
          <div className="rounded-xl border border-gray-200 bg-white p-6 dark:border-[#333] dark:bg-[#151515]">
            <p className="mb-4 text-gray-600 dark:text-gray-300">프로필 정보를 수정하려면 로그인하세요.</p>
            <button onClick={() => setLoginOpen(true)} className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">로그인하기</button>
          </div>
        )}
        <LocalPreferences />
      </div>
      <AuthModal isOpen={!token && loginOpen} onClose={() => setLoginOpen(false)} onLogin={() => setLoginOpen(false)} />
    </section>
  );
}

function ProfileEditor({ token }: { token: string }) {
  const [user, setUser] = useState<LeaderboardProfile | null>(null);
  const [profileNickname, setProfileNickname] = useState('');
  const [profileEmail, setProfileEmail] = useState('');
  const [profileAvatar, setProfileAvatar] = useState('');
  const [profileError, setProfileError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [saved, setSaved] = useState(false);
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const mounted = useRef(false);
  const saving = useRef(false);

  const fillFields = (profile: LeaderboardProfile) => {
    setProfileEmail(profile.email ?? '');
    setProfileNickname(profile.nickname ?? '');
    setProfileAvatar(profile.avatarUrl ?? '');
  };

  useEffect(() => {
    mounted.current = true;
    let active = true;
    setLoadError('');
    void getCurrentUser().then(value => {
      if (!active || currentToken() !== token) return;
      const profile = profileFromAuthUser(value);
      setUser(profile);
      fillFields(profile);
      saveLeaderboardProfile(profile);
    }).catch(error => {
      if (!active || currentToken() !== token) return;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setAuthToken(null);
      } else {
        setLoadError('프로필을 불러오지 못했습니다. 다시 시도해 주세요.');
      }
    });
    return () => { active = false; mounted.current = false; };
  }, [token, attempt]);

  const handleProfileSave = async (event: FormEvent) => {
    event.preventDefault();
    if (!user || saving.current) return;
    // A storage event can arrive after a click. Never send an old draft with
    // the new account's token, even during that notification gap.
    if (currentToken() !== token) {
      setAuthToken(currentToken());
      return;
    }
    saving.current = true;
    setIsProfileSaving(true);
    setProfileError('');
    setSaved(false);
    try {
      const profile = profileFromAuthUser(await updateProfile({
        email: profileEmail.trim() || null,
        nickname: profileNickname.trim() || null,
        avatarUrl: profileAvatar.trim() || null,
      }));
      if (!mounted.current || currentToken() !== token) return;
      setUser(profile);
      fillFields(profile);
      saveLeaderboardProfile(profile);
      setSaved(true);
    } catch (error) {
      if (!mounted.current || currentToken() !== token) return;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setAuthToken(null);
      } else {
        setProfileError(error instanceof Error ? error.message : '프로필 저장에 실패했습니다.');
      }
    } finally {
      saving.current = false;
      if (mounted.current && currentToken() === token) setIsProfileSaving(false);
    }
  };

  if (!user) return loadError ? (
    <div role="alert" className="rounded-xl border border-red-200 p-6 dark:border-red-900">
      <p>{loadError}</p>
      <button onClick={() => setAttempt(value => value + 1)} className="mt-3 text-blue-500 underline">다시 시도</button>
    </div>
  ) : <p role="status" className="text-gray-500 dark:text-gray-400">프로필을 불러오는 중...</p>;

  return (
    <div className="min-w-0 space-y-6">
      <p className="break-all text-sm text-gray-500 dark:text-gray-400">{user.username ?? user.name} · {user.role === 'admin' ? '관리자' : '사용자'}</p>
      <form onSubmit={handleProfileSave} onChange={() => setSaved(false)} className="space-y-4">
        <fieldset disabled={isProfileSaving} className="min-w-0 rounded-xl border border-gray-200 bg-white p-5 dark:border-[#333] dark:bg-[#151515] sm:p-6">
          <legend className="sr-only">프로필 정보</legend>
          <h2 className="text-lg font-bold">프로필 정보</h2>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">이메일, 닉네임, 아바타를 변경합니다.</p>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            {[
              { label: '이메일', value: profileEmail, set: setProfileEmail, type: 'email', placeholder: 'you@example.com' },
              { label: '닉네임', value: profileNickname, set: setProfileNickname, type: 'text', placeholder: '표시할 이름' },
              { label: '아바타 URL', value: profileAvatar, set: setProfileAvatar, type: 'text', placeholder: '비워두면 자동 생성' },
            ].map(field => (
              <label key={field.label} className={field.label === '아바타 URL' ? 'block sm:col-span-2' : 'block'}>
                <span className="text-sm font-medium">{field.label}</span>
                <input type={field.type} value={field.value} onChange={event => field.set(event.target.value)} placeholder={field.placeholder}
                  className="mt-2 w-full rounded-md border border-gray-300 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414]" />
              </label>
            ))}
          </div>
        </fieldset>
        {profileError && <p role="alert" className="text-sm text-red-500">{profileError}</p>}
        {saved && <p role="status" className="text-sm text-emerald-600 dark:text-emerald-400">프로필을 저장했습니다.</p>}
        <div className="flex justify-end gap-2 pb-4">
          <button type="button" disabled={isProfileSaving} onClick={() => { fillFields(user); setSaved(false); setProfileError(''); }}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50 dark:border-[#444] dark:text-gray-200 dark:hover:bg-[#252525]">취소</button>
          <button type="submit" disabled={isProfileSaving}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50">{isProfileSaving ? '저장 중...' : '저장'}</button>
        </div>
      </form>
    </div>
  );
}

function LocalPreferences() {
  const { autoSaveEnabled, setAutoSaveEnabled, theme, toggleTheme } = useCompilerStore();
  return (
    <div className="space-y-6">
      <section aria-labelledby="editor-settings-heading" className="rounded-xl border border-gray-200 bg-white p-5 dark:border-[#333] dark:bg-[#151515] sm:p-6">
        <h2 id="editor-settings-heading" className="text-lg font-bold">에디터 설정</h2>
        <label className="mt-5 flex items-center justify-between gap-4">
          <span><span className="block text-sm font-medium">자동저장</span><span className="mt-1 block text-xs text-gray-500 dark:text-gray-400">코드 변경 사항을 자동으로 저장합니다.</span></span>
          <input aria-label="자동저장" type="checkbox" checked={autoSaveEnabled} onChange={event => setAutoSaveEnabled(event.target.checked)} className="h-4 w-4 shrink-0" />
        </label>
      </section>
      <section aria-labelledby="display-settings-heading" className="rounded-xl border border-gray-200 bg-white p-5 dark:border-[#333] dark:bg-[#151515] sm:p-6">
        <h2 id="display-settings-heading" className="text-lg font-bold">화면 설정</h2>
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 text-sm">
          <label htmlFor="settings-theme">테마</label>
          <select id="settings-theme" value={theme} onChange={event => { if (event.target.value !== theme) toggleTheme(); }}
            className="rounded-md border border-gray-300 bg-gray-50 px-3 py-2 dark:border-[#444] dark:bg-[#222]">
            <option value="dark">다크</option><option value="light">라이트</option>
          </select>
        </div>
      </section>
      <p className="text-xs text-gray-500 dark:text-gray-400">자동저장과 테마는 변경하면 바로 적용됩니다.</p>
    </div>
  );
}
