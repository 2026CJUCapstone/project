import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import { Terminal, Play, Save, Square, Swords, Trophy, Settings } from 'lucide-react';
import { UserProfile } from './UserProfile';
import { AuthModal } from './AuthModal';

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const isIdeMode = location.pathname === '/';
  
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);
  const [user, setUser] = useState<{name: string, avatar: string} | null>(null);

  const handleLogin = (name: string, avatar: string) => {
    setUser({ name, avatar });
  };

  const handleLogout = () => {
    setUser(null);
  };

  return (
    <>
      <header className="flex items-center justify-between h-14 px-6 bg-[#1e1e1e] border-b border-[#333] shrink-0 shadow-md z-10">
        <div className="flex items-center gap-6">
          <button 
            onClick={() => navigate('/')} 
            className="flex items-center gap-3 hover:opacity-80 transition-opacity focus:outline-none"
          >
            <div className="flex items-center justify-center w-8 h-8 bg-blue-500/10 text-blue-400 rounded-lg shadow-inner">
              <Terminal size={18} strokeWidth={2.5} />
            </div>
            <span className="text-lg font-bold text-gray-100 tracking-wide select-none">
              B++ Online Compiler
            </span>
          </button>

          <div className="w-[1px] h-6 bg-[#444] mx-2"></div>

          {isIdeMode && (
            <div className="flex items-center gap-1.5 bg-[#252525] p-1 rounded-md border border-[#333]">
              <button className="p-1.5 text-gray-400 hover:text-white hover:bg-[#3d3d3d] rounded transition-colors" title="저장">
                <Save size={16} />
              </button>
              <button className="p-1.5 text-green-500 hover:text-green-400 hover:bg-[#3d3d3d] rounded transition-colors" title="코드 실행">
                <Play size={16} className="fill-current" />
              </button>
              <button className="p-1.5 text-red-500 hover:text-red-400 hover:bg-[#3d3d3d] rounded transition-colors" title="중지">
                <Square size={16} className="fill-current" />
              </button>
            </div>
          )}

          <div className="flex items-center gap-1 ml-2">
            <button 
              onClick={() => navigate('/challenges')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/challenges' 
                  ? 'bg-[#2d2d2d] text-white' 
                  : 'text-gray-300 hover:text-white hover:bg-[#2d2d2d]'
              }`}
            >
              <Swords size={16} className="text-blue-400" />
              챌린지
            </button>
            <button 
              onClick={() => navigate('/leaderboard')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
                location.pathname === '/leaderboard' 
                  ? 'bg-[#2d2d2d] text-white' 
                  : 'text-gray-300 hover:text-white hover:bg-[#2d2d2d]'
              }`}
            >
              <Trophy size={16} className="text-yellow-500" />
              리더보드
            </button>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button className="p-1.5 text-gray-400 hover:text-white hover:bg-[#2d2d2d] rounded-md transition-colors flex items-center gap-2" title="설정">
            <Settings size={18} />
          </button>
          
          <div className="w-[1px] h-6 bg-[#444]"></div>

          {user ? (
            <UserProfile 
              username={user.name} 
              avatarUrl={user.avatar} 
              onLogout={handleLogout}
            />
          ) : (
            <button 
              onClick={() => setIsAuthModalOpen(true)}
              className="px-5 py-1.5 bg-[#2d2d2d] hover:bg-[#3d3d3d] border border-[#444] text-gray-200 rounded-md text-sm font-medium transition-all shadow-sm active:scale-95"
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
