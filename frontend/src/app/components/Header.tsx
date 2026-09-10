import { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { Terminal, Play, Save, Square, Swords, Trophy, MessageSquare, Settings, Sun, Moon, Hammer, X, Activity, ClipboardList, Home, Code2, Menu } from 'lucide-react';
import { UserProfile } from './UserProfile';
import { AuthModal } from './AuthModal';
import { ProfileStatsPanel } from './ProfileStatsPanel';
import { useCompilerStore } from '../store/compilerStore';
import { getCurrentUser, updateProfile } from '../services/authApi';
import { saveCodeProject } from '../services/projectApi';
import { ApiError } from '../services/apiBase';
import { setAuthToken, subscribeAuthIdentity } from '../services/authIdentity';
import {
  clearLeaderboardProfile,
  getSavedLeaderboardProfile,
  profileFromAuthUser,
  saveLeaderboardProfile,
  type LeaderboardProfile,
} from '../services/leaderboardProfile';

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const isIdeMode = location.pathname === '/ide' || /^\/contests\/[^/]+\/problems\/[^/]+$/.test(location.pathname);
  
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const [user, setUser] = useState<LeaderboardProfile | null>(null);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [profileNickname, setProfileNickname] = useState('');
  const [profileEmail, setProfileEmail] = useState('');
  const [profileAvatar, setProfileAvatar] = useState('');
  const [profileError, setProfileError] = useState('');
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const profileDraftEdited = useRef(false);
  const profileReadVersion = useRef(0);
  const profileEditorToken = useRef<string | null>(null);
  const userSessionToken = useRef(localStorage.getItem('authToken'));
  const [authConnectionError, setAuthConnectionError] = useState(false);
  const [isRefreshingAuth, setIsRefreshingAuth] = useState(false);
  const [authRefreshAttempt, setAuthRefreshAttempt] = useState(0);
  const initialResetToken = new URLSearchParams(location.search).get('resetToken');
  
  const {
    theme,
    toggleTheme,
    code,
    codeStorageScope,
    codeStorageOwner,
    saveCode,
    addOutput,
    cancelRun,
    isRunning,
    compile,
    compileAndStartTerminal,
    isCompiling,
    isEditorReady,
    language,
    selectLanguage,
    autoSaveEnabled,
    setAutoSaveEnabled,
  } = useCompilerStore();

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  useEffect(() => {
    let observedToken = localStorage.getItem('authToken');
    return subscribeAuthIdentity(() => {
      const currentToken = localStorage.getItem('authToken');
      if (currentToken === observedToken) return;
      observedToken = currentToken;
      profileReadVersion.current += 1;
      profileEditorToken.current = null;
      userSessionToken.current = null;
      setIsProfileOpen(false);
      setIsProfileSaving(false);
      setProfileError('');
      setUser(null);
      clearLeaderboardProfile();
      setAuthConnectionError(false);
      setAuthRefreshAttempt(attempt => attempt + 1);
    });
  }, []);

  useEffect(() => {
    if (!localStorage.getItem('authToken')) {
      setUser(null);
      clearLeaderboardProfile();
      setIsRefreshingAuth(false);
      return;
    }
    const saved = getSavedLeaderboardProfile();
    if (saved) setUser(saved);

    let mounted = true;
    const checkedToken = localStorage.getItem('authToken');
    const checkedProfileVersion = profileReadVersion.current;
    const refreshCurrentUser = async () => {
      if (mounted) setIsRefreshingAuth(true);
      try {
        const current = profileFromAuthUser(await getCurrentUser());
        if (!mounted || localStorage.getItem('authToken') !== checkedToken
          || profileReadVersion.current !== checkedProfileVersion) return;
        setUser(current);
        userSessionToken.current = checkedToken;
        saveLeaderboardProfile(current);
        setAuthConnectionError(false);
      } catch (error) {
        if (!mounted || localStorage.getItem('authToken') !== checkedToken) return;
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setAuthToken(null);
          clearLeaderboardProfile();
          setUser(null);
          setAuthConnectionError(false);
        } else {
          // A network interruption or server error does not prove that the session expired.
          setAuthConnectionError(true);
        }
      } finally {
        if (mounted) setIsRefreshingAuth(false);
      }
    };
    void refreshCurrentUser();

    return () => {
      mounted = false;
    };
  }, [authRefreshAttempt]);

  useEffect(() => {
    if (!user || (isProfileOpen && profileDraftEdited.current)) return;
    setProfileNickname(user.nickname ?? '');
    setProfileEmail(user.email || '');
    setProfileAvatar(user.avatarUrl === undefined ? user.avatar : user.avatarUrl ?? '');
  }, [user, isProfileOpen]);

  useEffect(() => {
    if (initialResetToken) {
      setIsAuthModalOpen(true);
    }
  }, [initialResetToken]);

  const handleLogin = (profile: LeaderboardProfile) => {
    userSessionToken.current = localStorage.getItem('authToken');
    setUser(profile);
    saveLeaderboardProfile(profile);
  };

  const handleLogout = () => {
    profileReadVersion.current += 1;
    setIsProfileOpen(false);
    setUser(null);
    setAuthConnectionError(false);
    setAuthToken(null);
    clearLeaderboardProfile();
  };

  const openProfileSettings = async () => {
    if (!user) {
      setIsAuthModalOpen(true);
      return;
    }

    if (localStorage.getItem('authToken') !== userSessionToken.current) return;

    const readVersion = ++profileReadVersion.current;
    const checkedToken = localStorage.getItem('authToken');
    profileEditorToken.current = checkedToken;
    profileDraftEdited.current = false;
    setProfileError('');
    setIsProfileOpen(true);
    try {
      const current = profileFromAuthUser(await getCurrentUser());
      if (profileReadVersion.current !== readVersion
        || localStorage.getItem('authToken') !== checkedToken) return;
      setUser(current);
      saveLeaderboardProfile(current);
    } catch {
      // 프로필 편집 자체는 기존 로그인 상태 정보로 열어두고, 저장 시 서버 오류를 다시 표시한다.
    }
  };

  const closeProfileSettings = () => {
    profileReadVersion.current += 1;
    profileEditorToken.current = null;
    setIsProfileOpen(false);
  };

  const handleManualSave = async () => {
    saveCode(code, codeStorageScope);
    try {
      const savedRemote = await saveCodeProject(codeStorageScope, {
        code,
        language,
        title: codeStorageScope === 'main' ? '메인 화면' : codeStorageScope,
      }, codeStorageOwner);
      addOutput({
        type: 'success',
        text: savedRemote
          ? '> 코드가 서버와 로컬에 저장되었습니다.'
          : '> 코드가 로컬에 저장되었습니다. 서버 저장은 로그인 후 사용할 수 있습니다.',
      });
    } catch (error) {
      addOutput({
        type: 'warning',
        text: `> 로컬 저장은 완료됐지만 서버 저장에 실패했습니다: ${
          error instanceof Error ? error.message : '알 수 없는 오류'
        }`,
      });
    }
  };

  const handleProfileSave = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!user || isProfileSaving) return;
    // Storage events may arrive after a click in this tab. Never send the old
    // editor's draft using a token belonging to a different session.
    if (!profileEditorToken.current || localStorage.getItem('authToken') !== profileEditorToken.current) {
      closeProfileSettings();
      return;
    }
    // A read started before this write must not restore the old profile later.
    profileReadVersion.current += 1;
    const checkedToken = localStorage.getItem('authToken');
    setProfileError('');
    setIsProfileSaving(true);
    try {
      const updated = profileFromAuthUser(
        await updateProfile({
          email: profileEmail.trim() || null,
          nickname: profileNickname.trim() || null,
          avatarUrl: profileAvatar.trim() || null,
        }),
      );
      if (localStorage.getItem('authToken') !== checkedToken) return;
      setUser(updated);
      saveLeaderboardProfile(updated);
      setIsProfileOpen(false);
    } catch (error) {
      if (localStorage.getItem('authToken') !== checkedToken) return;
      setProfileError(error instanceof Error ? error.message : '프로필 저장에 실패했습니다.');
    } finally {
      if (localStorage.getItem('authToken') === checkedToken) setIsProfileSaving(false);
    }
  };

  return (
    <>
      <header className="relative flex h-14 shrink-0 items-center justify-between gap-3 border-b border-gray-200 bg-white px-3 shadow-sm transition-colors duration-200 dark:border-[#333] dark:bg-[#1e1e1e] sm:px-6 z-50">
        <div className="flex min-w-0 items-center gap-2 xl:gap-6">
          <button 
            onClick={() => navigate('/')} 
            className="flex shrink-0 items-center gap-2 hover:opacity-80 transition-opacity focus:outline-none sm:gap-3"
          >
            <div className="flex items-center justify-center w-8 h-8 bg-blue-100 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-lg shadow-inner">
              <Terminal size={18} strokeWidth={2.5} />
            </div>
            <span className="hidden text-lg font-bold text-gray-900 dark:text-gray-100 tracking-wide select-none sm:inline">
              B++ Online Compiler
            </span>
            <span className="text-base font-bold text-gray-900 dark:text-gray-100 sm:hidden">B++</span>
          </button>

          <div className="mx-2 hidden h-6 w-px bg-gray-200 dark:bg-[#444] xl:block"></div>

          {isIdeMode && (
            <div className="flex shrink-0 items-center gap-1 bg-gray-50 dark:bg-[#252525] p-1 rounded-md border border-gray-200 dark:border-[#333] transition-colors duration-200 sm:gap-1.5">
              <select
                value={language}
                onChange={(event) => selectLanguage(event.target.value as typeof language)}
                disabled={!isEditorReady || isCompiling || isRunning}
                className="bg-transparent text-xs font-medium text-gray-700 dark:text-gray-200 px-2 py-1.5 rounded outline-none"
                title="실행 언어 선택"
              >
                <option value="bpp">B++</option>
                <option value="cpp">C++</option>
                <option value="c">C</option>
                <option value="python">Python</option>
                <option value="java">Java</option>
                <option value="javascript">JavaScript</option>
              </select>
              <button
                onClick={() => {
                  void handleManualSave();
                }}
                className="hidden p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors sm:block"
                title="저장"
                disabled={!isEditorReady}
              >
                <Save size={16} />
              </button>
              <button
                onClick={() => { void compile(); }}
                disabled={!isEditorReady || isCompiling || isRunning}
                data-testid="compile-button"
                className="hidden p-1.5 text-orange-600 dark:text-orange-500 hover:text-orange-700 dark:hover:text-orange-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed sm:block"
                title="컴파일 (Ctrl+Shift+B)"
              >
                <Hammer size={16} />
              </button>
              <button
                onClick={() => {
                  void compileAndStartTerminal();
                }}
                disabled={!isEditorReady || isRunning || isCompiling}
                data-testid="compile-run-button"
                className="p-1.5 text-green-600 dark:text-green-500 hover:text-green-700 dark:hover:text-green-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="컴파일 & 실행 (Ctrl+Enter)"
              >
                <Play size={16} className="fill-current" />
              </button>
              <button
                onClick={cancelRun}
                disabled={!isRunning}
                className="hidden p-1.5 text-red-600 dark:text-red-500 hover:text-red-700 dark:hover:text-red-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed sm:block"
                title="중지"
              >
                <Square size={16} className="fill-current" />
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={() => setIsMobileNavOpen((open) => !open)}
            className={`ml-1 shrink-0 rounded-md p-2 text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-[#2d2d2d] ${isIdeMode ? 'min-[1680px]:hidden' : 'xl:hidden'}`}
            aria-label="메뉴 열기"
            aria-expanded={isMobileNavOpen}
          >
            {isMobileNavOpen ? <X size={19} /> : <Menu size={19} />}
          </button>

          <div className={`ml-2 hidden shrink-0 items-center gap-1 whitespace-nowrap ${isIdeMode ? 'min-[1680px]:flex' : 'xl:flex'}`}>
            <button
              onClick={() => navigate('/')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/'
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <Home size={16} className="text-slate-500 dark:text-slate-300" />
              홈
            </button>
            <button
              onClick={() => navigate('/ide')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/ide'
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <Code2 size={16} className="text-cyan-600 dark:text-cyan-400" />
              IDE
            </button>
            <button 
              onClick={() => navigate('/challenges')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
	                location.pathname.startsWith('/challenges')
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white' 
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <Swords size={16} className="text-blue-500 dark:text-blue-400" />
              챌린지
            </button>
            <button 
              onClick={() => navigate('/contests')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${location.pathname.startsWith('/contests') ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'}`}
            >
              <Trophy size={16} className="text-orange-500" />
              콘테스트
            </button>
            <button
              onClick={() => navigate('/leaderboard')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/leaderboard' 
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white' 
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <Trophy size={16} className="text-yellow-600 dark:text-yellow-500" />
              리더보드
            </button>
            <button
              onClick={() => navigate('/queue')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/queue'
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <Activity size={16} className="text-emerald-500 dark:text-emerald-400" />
              큐
            </button>
            <button
              onClick={() => navigate('/submissions')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/submissions'
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <ClipboardList size={16} className="text-sky-500 dark:text-sky-400" />
              제출
            </button>
            <button
              onClick={() => navigate('/community')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/community' 
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white' 
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <MessageSquare size={16} className="text-purple-500 dark:text-purple-400" />
              커뮤니티
            </button>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2 sm:gap-4">
          <button 
            onClick={toggleTheme}
            className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md transition-colors flex items-center gap-2" 
            title={theme === 'dark' ? "라이트 테마로 전환" : "다크 테마로 전환"}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          
          <button
            onClick={() => {
              void openProfileSettings();
            }}
            className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md transition-colors flex items-center gap-2"
            title="설정"
          >
            <Settings size={18} />
          </button>
          
          <div className="hidden h-6 w-px bg-gray-200 dark:bg-[#444] sm:block"></div>

          {user ? (
            <UserProfile 
              username={user.name} 
              avatarUrl={user.avatar} 
              role={user.role}
              onOpenProfile={() => {
                void openProfileSettings();
              }}
              onOpenSettings={() => {
                void openProfileSettings();
              }}
              onLogout={handleLogout}
            />
          ) : (
            <button 
              onClick={() => setIsAuthModalOpen(true)}
              className="px-3 py-1.5 bg-white dark:bg-[#2d2d2d] hover:bg-gray-50 dark:hover:bg-[#3d3d3d] border border-gray-200 dark:border-[#444] text-gray-700 dark:text-gray-200 rounded-md text-sm font-medium transition-all shadow-sm active:scale-95 sm:px-5"
            >
              로그인
            </button>
          )}
        </div>
      </header>

      {authConnectionError && (
        <div className="flex items-center justify-center gap-3 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-200" role="status">
          <span>로그인 정보를 확인하지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.</span>
          <button
            type="button"
            onClick={() => setAuthRefreshAttempt((attempt) => attempt + 1)}
            disabled={isRefreshingAuth}
            className="font-semibold underline disabled:opacity-60"
          >
            {isRefreshingAuth ? '확인 중...' : '다시 시도'}
          </button>
        </div>
      )}

      {isMobileNavOpen && (
        <nav className={`fixed inset-x-0 top-14 z-40 grid grid-cols-2 gap-2 border-b border-gray-200 bg-white p-3 shadow-xl dark:border-[#333] dark:bg-[#171717] sm:grid-cols-4 ${isIdeMode ? 'min-[1680px]:hidden' : 'xl:hidden'}`} aria-label="모바일 메뉴">
          {[
            { path: '/', label: '홈', icon: Home },
            { path: '/ide', label: 'IDE', icon: Code2 },
            { path: '/challenges', label: '챌린지', icon: Swords },
            { path: '/contests', label: '콘테스트', icon: Trophy },
            { path: '/leaderboard', label: '리더보드', icon: Trophy },
            { path: '/queue', label: '컴파일 큐', icon: Activity },
            { path: '/submissions', label: '제출 기록', icon: ClipboardList },
            { path: '/community', label: '커뮤니티', icon: MessageSquare },
          ].map(({ path, label, icon: Icon }) => {
            const active = path === '/' ? location.pathname === '/' : location.pathname.startsWith(path);
            return (
              <button
                key={path}
                type="button"
                onClick={() => {
                  navigate(path);
                  setIsMobileNavOpen(false);
                }}
                className={`flex items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-semibold ${
                  active
                    ? 'bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-300'
                    : 'text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-[#252525]'
                }`}
              >
                <Icon size={16} /> {label}
              </button>
            );
          })}
        </nav>
      )}

      <AuthModal 
        isOpen={isAuthModalOpen} 
        onClose={() => setIsAuthModalOpen(false)} 
        onLogin={handleLogin}
        initialResetToken={initialResetToken}
      />
      {isProfileOpen && user && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <form
            onSubmit={handleProfileSave}
            className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-[#333] dark:bg-[#1e1e1e]"
          >
            <div className="flex items-center justify-between border-b border-gray-200 px-6 py-5 dark:border-[#333]">
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-white">내 프로필</h2>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {user.username ?? user.name} · {user.role === 'admin' ? '관리자' : '사용자'}
                </p>
              </div>
              <button
                type="button"
                onClick={closeProfileSettings}
                className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100 dark:hover:bg-[#333]"
              >
                <X size={18} />
              </button>
            </div>

            <div className="space-y-6 p-6">
              <ProfileStatsPanel user={user} />

              <div className="rounded-lg border border-gray-200 bg-gray-50 p-5 dark:border-[#333] dark:bg-[#151515]">
                <div className="mb-4">
                  <h3 className="text-sm font-bold text-gray-900 dark:text-white">프로필 편집</h3>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    표시 정보와 자동저장 설정을 변경합니다.
                  </p>
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">이메일</span>
                <input
                  type="email"
                  value={profileEmail}
                  onChange={(event) => { profileDraftEdited.current = true; setProfileEmail(event.target.value); }}
                  className="mt-1 w-full rounded-md border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#141414] px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="you@example.com"
                />
                  </label>
                  <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">닉네임</span>
                <input
                  value={profileNickname}
                  onChange={(event) => { profileDraftEdited.current = true; setProfileNickname(event.target.value); }}
                  className="mt-1 w-full rounded-md border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#141414] px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="표시할 이름"
                />
                  </label>
                  <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">아바타 URL</span>
                <input
                  value={profileAvatar}
                  onChange={(event) => { profileDraftEdited.current = true; setProfileAvatar(event.target.value); }}
                  className="mt-1 w-full rounded-md border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#141414] px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="비워두면 자동 생성"
                />
                  </label>
                </div>
                <label className="mt-4 flex items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-2 dark:border-[#333] dark:bg-[#141414]">
                  <span className="text-sm text-gray-700 dark:text-gray-300">자동저장</span>
                  <input
                    type="checkbox"
                    checked={autoSaveEnabled}
                    onChange={(event) => setAutoSaveEnabled(event.target.checked)}
                    className="h-4 w-4"
                  />
                </label>
              </div>

              {profileError && <p className="text-xs text-red-500">{profileError}</p>}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeProfileSettings}
                className="px-4 py-2 text-sm rounded-md border border-gray-300 dark:border-[#444] text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-[#2d2d2d]"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={isProfileSaving}
                className="px-4 py-2 text-sm rounded-md bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
              >
                {isProfileSaving ? '저장 중...' : '저장'}
              </button>
            </div>
            </div>
          </form>
        </div>
      )}
    </>
  );
}
