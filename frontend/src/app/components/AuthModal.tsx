import { useState, useEffect } from 'react';
import { X, UserPlus, LogIn } from 'lucide-react';
import { createAvatarUrl } from '../services/leaderboardProfile';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLogin: (name: string, avatarUrl: string) => void;
}

export function AuthModal({ isOpen, onClose, onLogin }: AuthModalProps) {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');

  // Close on Escape key
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      window.addEventListener('keydown', handleEsc);
    }
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isLogin && password !== confirmPassword) {
      setPasswordError('비밀번호가 일치하지 않습니다.');
      return;
    }
    setPasswordError('');
    const emailName = email.split('@')[0]?.trim() || 'Coder';
    const name = (isLogin ? emailName : username.trim() || emailName).slice(0, 64);
    const avatarUrl = createAvatarUrl(name);
    
    onLogin(name, avatarUrl);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm animate-in fade-in duration-200 p-4">
      <div 
        className="relative w-full max-w-sm p-8 bg-white dark:bg-[#1e1e1e] border border-gray-200 dark:border-[#333] rounded-2xl shadow-2xl animate-in zoom-in-95 duration-200 transition-colors"
      >
        <button 
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#333] hover:text-gray-900 dark:hover:text-white rounded-md transition-colors"
        >
          <X size={20} />
        </button>

        <div className="flex flex-col items-center mb-8">
          <div className="flex items-center justify-center w-12 h-12 bg-blue-100 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-full mb-4 shadow-inner">
            {isLogin ? <LogIn size={24} /> : <UserPlus size={24} />}
          </div>
          <h2 className="text-2xl font-bold text-center text-gray-900 dark:text-white">
            {isLogin ? '로그인' : '회원가입'}
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 text-center">
            {isLogin 
              ? 'B++ 컴파일러에 로그인하세요' 
              : '가입하여 B++ 프로젝트를 저장하세요'
            }
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {!isLogin && (
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">사용자 이름</label>
              <input 
                type="text" 
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                placeholder="developer_123"
              />
            </div>
          )}
          
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">이메일 주소</label>
            <input 
              type="email" 
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
              placeholder="you@example.com"
            />
          </div>
          
          <div className="space-y-1.5">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 flex justify-between">
              비밀번호
              {isLogin && <button type="button" className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300">비밀번호 찾기</button>}
            </label>
            <input 
              type="password" 
              required
              value={password}
              onChange={(e) => { setPassword(e.target.value); setPasswordError(''); }}
              className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
              placeholder="••••••••"
            />
          </div>

          {!isLogin && (
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">비밀번호 확인</label>
              <input 
                type="password" 
                required
                value={confirmPassword}
                onChange={(e) => { setConfirmPassword(e.target.value); setPasswordError(''); }}
                className={`w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all ${
                  passwordError ? 'border-red-500 focus:border-red-500' : 'border-gray-300 dark:border-[#333] focus:border-blue-500'
                }`}
                placeholder="••••••••"
              />
              {passwordError && (
                <p className="text-xs text-red-500 mt-1">{passwordError}</p>
              )}
            </div>
          )}

          <button 
            type="submit"
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 dark:hover:bg-blue-500 text-white font-medium rounded-lg shadow-lg shadow-blue-500/20 transition-all active:scale-[0.98] mt-2"
          >
            {isLogin ? '로그인' : '계정 생성'}
          </button>
        </form>

        <div className="mt-8 text-center text-sm text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-[#333] pt-6 transition-colors">
          {isLogin ? "계정이 없으신가요? " : "이미 계정이 있으신가요? "}
          <button 
            type="button"
            onClick={() => { setIsLogin(!isLogin); setPassword(''); setConfirmPassword(''); setPasswordError(''); }}
            className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium"
          >
            {isLogin ? '회원가입' : '로그인'}
          </button>
        </div>
      </div>
    </div>
  );
}
