import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { Terminal, Play, Save, Square, Swords, Trophy, MessageSquare, Settings, Sun, Moon, Hammer, X, Activity, ClipboardList } from 'lucide-react';
import { UserProfile } from './UserProfile';
import { AuthModal } from './AuthModal';
import { useCompilerStore } from '../store/compilerStore';
import { getCurrentUser, updateProfile } from '../services/authApi';
import { saveCodeProject } from '../services/projectApi';
import { getProblemTagLabel } from '../constants/problemTags';
import {
  clearLeaderboardProfile,
  getSavedLeaderboardProfile,
  profileFromAuthUser,
  saveLeaderboardProfile,
  type LeaderboardProfile,
} from '../services/leaderboardProfile';

function formatDifficulty(difficulty?: string | null) {
  if (!difficulty) return '기록 없음';
  return difficulty.replace(/([a-z]+)(\d+)/i, (_, family: string, level: string) => {
    const label = family.charAt(0).toUpperCase() + family.slice(1);
    return `${label} ${level}`;
  });
}

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const isIdeMode = location.pathname === '/';
  
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [user, setUser] = useState<LeaderboardProfile | null>(null);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [profileNickname, setProfileNickname] = useState('');
  const [profileEmail, setProfileEmail] = useState('');
  const [profileAvatar, setProfileAvatar] = useState('');
  const [profileError, setProfileError] = useState('');
  const [isProfileSaving, setIsProfileSaving] = useState(false);
  const initialResetToken = new URLSearchParams(location.search).get('resetToken');
  
  const {
    theme,
    toggleTheme,
    code,
    codeStorageScope,
    saveCode,
    addOutput,
    cancelRun,
    isRunning,
    compile,
    compileAndStartTerminal,
    isCompiling,
    language,
    setLanguage,
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
    const saved = getSavedLeaderboardProfile();
    if (saved) setUser(saved);

    if (!localStorage.getItem('authToken')) return;

    let mounted = true;
    (async () => {
      try {
        const current = profileFromAuthUser(await getCurrentUser());
        if (!mounted) return;
        setUser(current);
        saveLeaderboardProfile(current);
      } catch {
        if (!mounted) return;
        localStorage.removeItem('authToken');
        clearLeaderboardProfile();
        setUser(null);
      }
    })();

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    setProfileNickname(user.nickname || user.name || '');
    setProfileEmail(user.email || '');
    setProfileAvatar(user.avatar || '');
  }, [user]);

  useEffect(() => {
    if (initialResetToken) {
      setIsAuthModalOpen(true);
    }
  }, [initialResetToken]);

  const handleLogin = (profile: LeaderboardProfile) => {
    setUser(profile);
    saveLeaderboardProfile(profile);
  };

  const handleLogout = () => {
    setUser(null);
    localStorage.removeItem('authToken');
    clearLeaderboardProfile();
  };

  const openProfileSettings = async () => {
    if (!user) {
      setIsAuthModalOpen(true);
      return;
    }

    setIsProfileOpen(true);
    try {
      const current = profileFromAuthUser(await getCurrentUser());
      setUser(current);
      saveLeaderboardProfile(current);
    } catch {
      // 프로필 편집 자체는 기존 로그인 상태 정보로 열어두고, 저장 시 서버 오류를 다시 표시한다.
    }
  };

  const handleManualSave = async () => {
    saveCode(code, codeStorageScope);
    try {
      const savedRemote = await saveCodeProject(codeStorageScope, {
        code,
        language,
        title: codeStorageScope === 'main' ? '메인 화면' : codeStorageScope,
      });
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
      setUser(updated);
      saveLeaderboardProfile(updated);
      setIsProfileOpen(false);
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : '프로필 저장에 실패했습니다.');
    } finally {
      setIsProfileSaving(false);
    }
  };

  return (
    <>
      <header className="flex items-center justify-between h-14 px-6 bg-white dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0 shadow-sm z-10 transition-colors duration-200">
        <div className="flex items-center gap-6">
          <button 
            onClick={() => navigate('/')} 
            className="flex items-center gap-3 hover:opacity-80 transition-opacity focus:outline-none"
          >
            <div className="flex items-center justify-center w-8 h-8 bg-blue-100 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-lg shadow-inner">
              <Terminal size={18} strokeWidth={2.5} />
            </div>
            <span className="text-lg font-bold text-gray-900 dark:text-gray-100 tracking-wide select-none">
              B++ Online Compiler
            </span>
          </button>

          <div className="w-[1px] h-6 bg-gray-200 dark:bg-[#444] mx-2"></div>

          {isIdeMode && (
            <div className="flex items-center gap-1.5 bg-gray-50 dark:bg-[#252525] p-1 rounded-md border border-gray-200 dark:border-[#333] transition-colors duration-200">
              <select
                value={language}
                onChange={(event) => setLanguage(event.target.value as typeof language)}
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
              >
                <Save size={16} />
              </button>
              <button
                onClick={() => { void compile(); }}
                disabled={isCompiling || isRunning}
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
                disabled={isRunning || isCompiling}
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

          <div className="flex items-center gap-1 ml-2">
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

        <div className="flex items-center gap-4">
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
          
          <div className="w-[1px] h-6 bg-gray-200 dark:bg-[#444]"></div>

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
              className="px-5 py-1.5 bg-white dark:bg-[#2d2d2d] hover:bg-gray-50 dark:hover:bg-[#3d3d3d] border border-gray-200 dark:border-[#444] text-gray-700 dark:text-gray-200 rounded-md text-sm font-medium transition-all shadow-sm active:scale-95"
            >
              로그인
            </button>
          )}
        </div>
      </header>

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
            className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg border border-gray-200 bg-white p-6 shadow-2xl dark:border-[#333] dark:bg-[#1e1e1e]"
          >
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-lg font-bold text-gray-900 dark:text-white">프로필 설정</h2>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  {user.username ?? user.name} · {user.role === 'admin' ? '관리자' : '사용자'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsProfileOpen(false)}
                className="p-1.5 rounded-md text-gray-500 hover:bg-gray-100 dark:hover:bg-[#333]"
              >
                <X size={18} />
              </button>
            </div>

            <div className="mb-5 grid grid-cols-2 gap-x-4 gap-y-3 border-y border-gray-200 py-3 dark:border-[#333] sm:grid-cols-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Rating</p>
                <p className="mt-1 font-mono text-lg font-bold text-blue-600 dark:text-blue-400">
                  {(user.rating ?? 0).toLocaleString()}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Tier</p>
                <p className="mt-1 truncate text-sm font-bold text-gray-900 dark:text-white">{user.tier ?? 'Unrated'}</p>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Solved</p>
                <p className="mt-1 font-mono text-lg font-bold text-emerald-600 dark:text-emerald-400">
                  {(user.solvedCount ?? 0).toLocaleString()}
                </p>
              </div>
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">XP</p>
                <p className="mt-1 font-mono text-lg font-bold text-gray-700 dark:text-gray-200">
                  {(user.totalScore ?? 0).toLocaleString()}
                </p>
              </div>
            </div>

            <div className="mb-5 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-[#333] dark:bg-[#151515]">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-bold text-gray-900 dark:text-white">태그 숙련도</h3>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  해결 난이도 합산 기준
                </span>
              </div>
              {user.tagProficiencies?.length ? (
                <div className="space-y-3">
                  {user.tagProficiencies.map((item) => (
                    <div key={item.tag}>
                      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
                        <span className="font-semibold text-gray-700 dark:text-gray-200">
                          {getProblemTagLabel(item.tag)}
                        </span>
                        <span className="font-mono text-gray-500 dark:text-gray-400">
                          {item.solvedCount} solved · {item.difficultyScore} pts · 최고 {formatDifficulty(item.maxDifficulty)}
                        </span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-gray-200 dark:bg-[#2a2a2a]">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500"
                          style={{ width: `${Math.max(4, Math.min(100, item.proficiency))}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="rounded-md border border-dashed border-gray-300 px-3 py-4 text-center text-sm text-gray-500 dark:border-[#444] dark:text-gray-400">
                  아직 태그 숙련도를 계산할 accepted 기록이 없습니다.
                </p>
              )}
            </div>

            <div className="space-y-4">
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">이메일</span>
                <input
                  type="email"
                  value={profileEmail}
                  onChange={(event) => setProfileEmail(event.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#141414] px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="you@example.com"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">닉네임</span>
                <input
                  value={profileNickname}
                  onChange={(event) => setProfileNickname(event.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#141414] px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="표시할 이름"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">아바타 URL</span>
                <input
                  value={profileAvatar}
                  onChange={(event) => setProfileAvatar(event.target.value)}
                  className="mt-1 w-full rounded-md border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#141414] px-3 py-2 text-sm text-gray-900 dark:text-white outline-none focus:border-blue-500"
                  placeholder="비워두면 자동 생성"
                />
              </label>
              <label className="flex items-center justify-between rounded-md border border-gray-200 dark:border-[#333] px-3 py-2">
                <span className="text-sm text-gray-700 dark:text-gray-300">자동저장</span>
                <input
                  type="checkbox"
                  checked={autoSaveEnabled}
                  onChange={(event) => setAutoSaveEnabled(event.target.checked)}
                  className="h-4 w-4"
                />
              </label>
            </div>

            {profileError && <p className="mt-3 text-xs text-red-500">{profileError}</p>}

            <div className="flex justify-end gap-2 mt-6">
              <button
                type="button"
                onClick={() => setIsProfileOpen(false)}
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
          </form>
        </div>
      )}
    </>
  );
}
