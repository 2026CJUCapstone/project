import { useEffect, useState } from 'react';
import { ArrowLeft, KeyRound, LogIn, Mail, UserPlus, X } from 'lucide-react';
import {
  confirmPasswordReset,
  getCurrentUser,
  login,
  register,
  requestPasswordReset,
} from '../services/authApi';
import { profileFromAuthUser, type LeaderboardProfile } from '../services/leaderboardProfile';

type AuthMode = 'login' | 'register' | 'forgot' | 'reset';

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onLogin: (profile: LeaderboardProfile) => void;
  initialResetToken?: string | null;
}

const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function AuthModal({ isOpen, onClose, onLogin, initialResetToken }: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>(initialResetToken ? 'reset' : 'login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [nickname, setNickname] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [resetIdentity, setResetIdentity] = useState('');
  const [resetToken, setResetToken] = useState(initialResetToken || '');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [authError, setAuthError] = useState('');
  const [notice, setNotice] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    if (isOpen) {
      window.addEventListener('keydown', handleEsc);
    }
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen || !initialResetToken) return;
    setResetToken(initialResetToken);
    setMode('reset');
  }, [initialResetToken, isOpen]);

  if (!isOpen) return null;

  const isLogin = mode === 'login';
  const isRegister = mode === 'register';
  const title =
    mode === 'login'
      ? '로그인'
      : mode === 'register'
        ? '회원가입'
        : mode === 'forgot'
          ? '비밀번호 재설정'
          : '새 비밀번호 설정';
  const subtitle =
    mode === 'login'
      ? 'B++ 컴파일러에 로그인하세요'
      : mode === 'register'
        ? '가입하여 B++ 프로젝트를 저장하세요'
        : mode === 'forgot'
          ? '가입한 이메일로 재설정 토큰을 받습니다'
          : '메일로 받은 토큰과 새 비밀번호를 입력하세요';
  const icon =
    mode === 'login' ? (
      <LogIn size={24} />
    ) : mode === 'register' ? (
      <UserPlus size={24} />
    ) : mode === 'forgot' ? (
      <Mail size={24} />
    ) : (
      <KeyRound size={24} />
    );

  const clearFeedback = () => {
    setAuthError('');
    setPasswordError('');
    setNotice('');
  };

  const switchMode = (nextMode: AuthMode) => {
    clearFeedback();
    setMode(nextMode);
    setPassword('');
    setConfirmPassword('');
    setNewPassword('');
    setConfirmNewPassword('');
  };

  const handleCredentialSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;

    clearFeedback();
    if (isRegister && password !== confirmPassword) {
      setPasswordError('비밀번호가 일치하지 않습니다.');
      return;
    }

    const normalizedUsername = username.trim().slice(0, 64);
    const normalizedEmail = email.trim().toLowerCase();

    try {
      setIsSubmitting(true);

      if (normalizedUsername.length < 3) {
        throw new Error('사용자 이름은 3자 이상이어야 합니다.');
      }
      if (password.length < 8) {
        throw new Error('비밀번호는 8자 이상이어야 합니다.');
      }
      if (isRegister && !EMAIL_PATTERN.test(normalizedEmail)) {
        throw new Error('올바른 이메일 주소를 입력하세요.');
      }

      if (isLogin) {
        const token = await login(normalizedUsername, password);
        localStorage.setItem('authToken', token.accessToken);
      } else {
        await register(normalizedUsername, normalizedEmail, password, nickname.trim() || undefined);
        const token = await login(normalizedUsername, password);
        localStorage.setItem('authToken', token.accessToken);
      }

      const user = await getCurrentUser();
      onLogin(profileFromAuthUser(user));
      onClose();
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '인증 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetRequest = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;

    clearFeedback();
    const identity = resetIdentity.trim();
    try {
      setIsSubmitting(true);
      if (identity.length < 3) {
        throw new Error('아이디 또는 이메일을 입력하세요.');
      }

      const response = await requestPasswordReset(identity);
      if (response.debugResetToken) {
        setResetToken(response.debugResetToken);
        setMode('reset');
      }
      setNotice(response.message);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '재설정 요청에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResetConfirm = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;

    clearFeedback();
    if (newPassword !== confirmNewPassword) {
      setPasswordError('비밀번호가 일치하지 않습니다.');
      return;
    }

    try {
      setIsSubmitting(true);
      if (!resetToken.trim()) {
        throw new Error('재설정 토큰을 입력하세요.');
      }
      if (newPassword.length < 8) {
        throw new Error('비밀번호는 8자 이상이어야 합니다.');
      }

      const response = await confirmPasswordReset(resetToken.trim(), newPassword);
      setMode('login');
      setPassword('');
      setConfirmPassword('');
      setNewPassword('');
      setConfirmNewPassword('');
      setResetToken('');
      setNotice(`${response.message} 새 비밀번호로 로그인하세요.`);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : '비밀번호 변경에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm animate-in fade-in duration-200 p-4">
      <div className="relative w-full max-w-md p-8 bg-white dark:bg-[#1e1e1e] border border-gray-200 dark:border-[#333] rounded-lg shadow-2xl animate-in zoom-in-95 duration-200 transition-colors">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#333] hover:text-gray-900 dark:hover:text-white rounded-md transition-colors"
          title="닫기"
        >
          <X size={20} />
        </button>

        <div className="flex flex-col items-center mb-8">
          <div className="flex items-center justify-center w-12 h-12 bg-blue-100 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 rounded-full mb-4 shadow-inner">
            {icon}
          </div>
          <h2 className="text-2xl font-bold text-center text-gray-900 dark:text-white">{title}</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 text-center">{subtitle}</p>
        </div>

        {(isLogin || isRegister) && (
          <form onSubmit={handleCredentialSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">사용자 이름</label>
              <input
                type="text"
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                placeholder="developer_123"
              />
            </div>

            {isRegister && (
              <>
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">이메일</label>
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                    placeholder="you@example.com"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                    닉네임 <span className="text-gray-400 dark:text-gray-500 font-normal">(선택)</span>
                  </label>
                  <input
                    type="text"
                    value={nickname}
                    onChange={(event) => setNickname(event.target.value)}
                    className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                    placeholder="표시될 이름"
                  />
                </div>
              </>
            )}

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">비밀번호</label>
              <input
                type="password"
                required
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setPasswordError('');
                }}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                placeholder="••••••••"
              />
            </div>

            {isRegister && (
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">비밀번호 확인</label>
                <input
                  type="password"
                  required
                  value={confirmPassword}
                  onChange={(event) => {
                    setConfirmPassword(event.target.value);
                    setPasswordError('');
                  }}
                  className={`w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all ${
                    passwordError ? 'border-red-500 focus:border-red-500' : 'border-gray-300 dark:border-[#333] focus:border-blue-500'
                  }`}
                  placeholder="••••••••"
                />
                {passwordError && <p className="text-xs text-red-500 mt-1">{passwordError}</p>}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 dark:hover:bg-blue-500 text-white font-medium rounded-lg shadow-lg shadow-blue-500/20 transition-all active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isSubmitting ? '처리 중...' : isLogin ? '로그인' : '계정 생성'}
            </button>
          </form>
        )}

        {mode === 'forgot' && (
          <form onSubmit={handleResetRequest} className="space-y-5">
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">아이디 또는 이메일</label>
              <input
                type="text"
                required
                value={resetIdentity}
                onChange={(event) => setResetIdentity(event.target.value)}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                placeholder="developer_123 또는 you@example.com"
              />
            </div>
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 dark:hover:bg-blue-500 text-white font-medium rounded-lg shadow-lg shadow-blue-500/20 transition-all active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isSubmitting ? '처리 중...' : '재설정 메일 보내기'}
            </button>
          </form>
        )}

        {mode === 'reset' && (
          <form onSubmit={handleResetConfirm} className="space-y-5">
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">재설정 토큰</label>
              <input
                type="text"
                required
                value={resetToken}
                onChange={(event) => setResetToken(event.target.value)}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                placeholder="메일의 토큰"
              />
            </div>
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">새 비밀번호</label>
              <input
                type="password"
                required
                value={newPassword}
                onChange={(event) => {
                  setNewPassword(event.target.value);
                  setPasswordError('');
                }}
                className="w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border border-gray-300 dark:border-[#333] rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 transition-all"
                placeholder="••••••••"
              />
            </div>
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">새 비밀번호 확인</label>
              <input
                type="password"
                required
                value={confirmNewPassword}
                onChange={(event) => {
                  setConfirmNewPassword(event.target.value);
                  setPasswordError('');
                }}
                className={`w-full px-4 py-2.5 bg-gray-50 dark:bg-[#141414] border rounded-lg text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/50 transition-all ${
                  passwordError ? 'border-red-500 focus:border-red-500' : 'border-gray-300 dark:border-[#333] focus:border-blue-500'
                }`}
                placeholder="••••••••"
              />
              {passwordError && <p className="text-xs text-red-500 mt-1">{passwordError}</p>}
            </div>
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 dark:hover:bg-blue-500 text-white font-medium rounded-lg shadow-lg shadow-blue-500/20 transition-all active:scale-[0.98] disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isSubmitting ? '처리 중...' : '비밀번호 변경'}
            </button>
          </form>
        )}

        {notice && <p className="mt-4 text-xs text-green-600 dark:text-green-400">{notice}</p>}
        {authError && <p className="mt-4 text-xs text-red-500">{authError}</p>}

        <div className="mt-8 text-center text-sm text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-[#333] pt-6 transition-colors">
          {isLogin && (
            <div className="flex items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => switchMode('forgot')}
                className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium"
              >
                비밀번호 찾기
              </button>
              <button
                type="button"
                onClick={() => switchMode('register')}
                className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium"
              >
                회원가입
              </button>
            </div>
          )}
          {isRegister && (
            <>
              이미 계정이 있으신가요?{' '}
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium"
              >
                로그인
              </button>
            </>
          )}
          {(mode === 'forgot' || mode === 'reset') && (
            <button
              type="button"
              onClick={() => switchMode('login')}
              className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium"
            >
              <ArrowLeft size={14} />
              로그인으로 돌아가기
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
