import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { Terminal, Play, Save, Square, Swords, Trophy, Settings, Sun, Moon } from 'lucide-react';
import { UserProfile } from './UserProfile';
import { AuthModal } from './AuthModal';
import { useCompilerStore } from '../store/compilerStore';

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const isIdeMode = location.pathname === '/';
  
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [user, setUser] = useState<{name: string, avatar: string} | null>(null);
  
  const { theme, toggleTheme } = useCompilerStore();

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const handleLogin = (name: string, avatar: string) => {
    setUser({ name, avatar });
  };

  const handleLogout = () => {
    setUser(null);
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
              <button className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors" title="저장">
                <Save size={16} />
              </button>
              <button className="p-1.5 text-green-600 dark:text-green-500 hover:text-green-700 dark:hover:text-green-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors" title="코드 실행">
                <Play size={16} className="fill-current" />
              </button>
              <button className="p-1.5 text-red-600 dark:text-red-500 hover:text-red-700 dark:hover:text-red-400 hover:bg-gray-200 dark:hover:bg-[#3d3d3d] rounded transition-colors" title="중지">
                <Square size={16} className="fill-current" />
              </button>
            </div>
          )}

          <div className="flex items-center gap-1 ml-2">
            <button 
              onClick={() => navigate('/challenges')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/challenges' 
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
          
          <button className="p-1.5 text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-[#2d2d2d] rounded-md transition-colors flex items-center gap-2" title="설정">
            <Settings size={18} />
          </button>
          
          <div className="w-[1px] h-6 bg-gray-200 dark:bg-[#444]"></div>

          {user ? (
            <UserProfile 
              username={user.name} 
              avatarUrl={user.avatar} 
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
      />
    </>
  );
}
