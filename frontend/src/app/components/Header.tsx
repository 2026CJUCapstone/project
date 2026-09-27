import { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { Terminal, Play, Save, Square, Swords, Trophy, MessageSquare, Settings, Sun, Moon, Hammer, X, Activity, ClipboardList, Home, Code2, Menu } from 'lucide-react';
import { UserProfile } from './UserProfile';
import { AuthModal } from './AuthModal';
import { useCompilerStore } from '../store/compilerStore';
import { getCurrentUser } from '../services/authApi';
import { saveCodeProject } from '../services/projectApi';
import { ApiError } from '../services/apiBase';
import { setAuthToken, subscribeAuthIdentity } from '../services/authIdentity';
import {
  clearLeaderboardProfile,
  subscribeLeaderboardProfile,
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
  const profileReadVersion = useRef(0);
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
      userSessionToken.current = null;
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
        if (!mounted || localStorage.getItem('authToken') !== checkedToken
          || profileReadVersion.current !== checkedProfileVersion) return;
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

  useEffect(() => subscribeLeaderboardProfile(() => {
    if (!localStorage.getItem('authToken')) return;
    profileReadVersion.current += 1;
    userSessionToken.current = localStorage.getItem('authToken');
    setUser(getSavedLeaderboardProfile());
  }), []);

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
    setUser(null);
    setAuthConnectionError(false);
    setAuthToken(null);
    clearLeaderboardProfile();
  };

  const openProfile = () => {
    if (!user) {
      setIsAuthModalOpen(true);
      return;
    }
    if (localStorage.getItem('authToken') !== userSessionToken.current) return;
    setIsMobileNavOpen(false);
    navigate('/profile');
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

  return (
    <>
      <header data-testid="site-header" className="relative flex h-14 shrink-0 items-center justify-between gap-3 border-b border-gray-200 bg-white px-3 shadow-sm transition-colors duration-200 dark:border-[#333] dark:bg-[#1e1e1e] sm:px-6 z-50">
        <div className="flex min-w-0 items-center gap-2 xl:gap-4">
          <button 
            aria-label="B++ Online Compiler"
            onClick={() => navigate('/')} 
            className="flex shrink-0 items-center gap-2 hover:opacity-80 transition-opacity focus:outline-none sm:gap-3"
          >
            <div className="flex items-center justify-center w-8 h-8 bg-blue-100 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-lg shadow-inner">
              <Terminal size={18} strokeWidth={2.5} />
            </div>
            <span className="hidden text-lg font-bold text-gray-900 dark:text-gray-100 tracking-wide select-none lg:inline">
              B++ Online Compiler
            </span>
            <span className="hidden min-[360px]:inline text-base font-bold text-gray-900 dark:text-gray-100 lg:hidden">B++</span>
          </button>

          <div className="mx-2 hidden h-6 w-px bg-gray-200 dark:bg-[#444] min-[1680px]:block"></div>



          <button
            type="button"
            onClick={() => setIsMobileNavOpen((open) => !open)}
            className="ml-1 shrink-0 rounded-md p-2 text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-[#2d2d2d] min-[1440px]:hidden"
            aria-label="메뉴 열기"
            aria-expanded={isMobileNavOpen}
          >
            {isMobileNavOpen ? <X size={19} /> : <Menu size={19} />}
          </button>

          <div className="ml-2 hidden shrink-0 items-center gap-1 whitespace-nowrap min-[1440px]:flex">
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
              onClick={() => navigate('/problems')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname.startsWith('/problems') || location.pathname.startsWith('/challenges')
                  ? 'bg-gray-100 dark:bg-[#2d2d2d] text-gray-900 dark:text-white' 
                  : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'
              }`}
            >
              <Swords size={16} className="text-blue-500 dark:text-blue-400" />
              문제
            </button>
            <button onClick={() => navigate('/learning')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md flex items-center gap-2 ${location.pathname === '/learning' ? 'bg-gray-100 dark:bg-[#2d2d2d] text-blue-500' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#2d2d2d]'}`}>
              <Code2 size={16} className="text-emerald-500" /> 학습
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

        <div className="flex shrink-0 items-center gap-2 sm:gap-3">
          <button 
            onClick={toggleTheme}
            className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md transition-colors flex items-center gap-2" 
            title={theme === 'dark' ? "라이트 테마로 전환" : "다크 테마로 전환"}
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          
          <button
            onClick={() => {
              setIsMobileNavOpen(false);
              navigate('/settings');
            }}
            className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md transition-colors flex items-center gap-2"
            title="설정"
          >
            <Settings size={18} />
          </button>
          
          <div className="hidden h-6 w-px bg-gray-200 dark:bg-[#444] lg:block"></div>

          {user ? (
            <UserProfile 
              username={user.name} 
              avatarUrl={user.avatar} 
              role={user.role}
              onOpenProfile={() => {
                openProfile();
              }}
              onOpenSettings={() => {
                setIsMobileNavOpen(false);
                navigate('/settings');
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

      {isIdeMode && (
            <div data-testid="ide-toolbar" className="flex w-full shrink-0 items-center justify-start gap-1 bg-gray-50 dark:bg-[#252525] px-3 py-1.5 border-b border-gray-200 dark:border-[#333] transition-colors duration-200 sm:gap-1.5 sm:px-6">
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
                className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors"
                title="저장"
                disabled={!isEditorReady}
              >
                <Save size={16} />
              </button>
              <button
                onClick={() => { void compile(); }}
                disabled={!isEditorReady || isCompiling || isRunning}
                data-testid="compile-button"
                className="p-1.5 text-orange-600 dark:text-orange-500 hover:text-orange-700 dark:hover:text-orange-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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
                className="p-1.5 text-red-600 dark:text-red-500 hover:text-red-700 dark:hover:text-red-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="중지"
              >
                <Square size={16} className="fill-current" />
              </button>
            </div>
          )}

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
        <nav className="fixed inset-x-0 top-14 z-40 grid grid-cols-2 gap-2 border-b border-gray-200 bg-white p-3 shadow-xl dark:border-[#333] dark:bg-[#171717] sm:grid-cols-4 min-[1440px]:hidden" aria-label="모바일 메뉴">
          {[
            { path: '/', label: '홈', icon: Home },
            { path: '/ide', label: 'IDE', icon: Code2 },
            { path: '/problems', label: '문제', icon: Swords },
            { path: '/learning', label: '학습', icon: Code2 },
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
    </>
  );
}
