import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthModal } from './AuthModal';

vi.mock('../services/authApi', () => ({
  confirmPasswordReset: vi.fn(),
  getCurrentUser: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  requestPasswordReset: vi.fn(),
}));
vi.mock('../services/authIdentity', () => ({ setAuthToken: vi.fn() }));
vi.mock('../services/leaderboardProfile', () => ({ profileFromAuthUser: vi.fn() }));

afterEach(cleanup);

const renderOpenModal = () =>
  render(<AuthModal isOpen={true} onClose={vi.fn()} onLogin={vi.fn()} />);

describe('AuthModal form accessibility', () => {
  it('associates the login labels with their inputs', () => {
    renderOpenModal();

    expect(screen.getByLabelText('사용자 이름')).toBeInTheDocument();
    expect(screen.getByLabelText('비밀번호')).toBeInTheDocument();
  });

  it('associates every registration label with its input', () => {
    renderOpenModal();
    fireEvent.click(screen.getByRole('button', { name: '회원가입' }));

    expect(screen.getByLabelText('사용자 이름')).toBeInTheDocument();
    expect(screen.getByLabelText('이메일')).toBeInTheDocument();
    expect(screen.getByLabelText(/닉네임\s+\(선택\)/)).toBeInTheDocument();
    expect(screen.getByLabelText('비밀번호')).toBeInTheDocument();
    expect(screen.getByLabelText('비밀번호 확인')).toBeInTheDocument();
  });

  it('associates the password-request label with its input', () => {
    renderOpenModal();
    fireEvent.click(screen.getByRole('button', { name: '비밀번호 찾기' }));

    expect(screen.getByLabelText('아이디 또는 이메일')).toBeInTheDocument();
  });

  it('associates every password-reset label with its input', () => {
    render(
      <AuthModal
        isOpen={true}
        onClose={vi.fn()}
        onLogin={vi.fn()}
        initialResetToken="fixture-reset-token"
      />,
    );

    expect(screen.getByLabelText('재설정 토큰')).toBeInTheDocument();
    expect(screen.getByLabelText('새 비밀번호')).toBeInTheDocument();
    expect(screen.getByLabelText('새 비밀번호 확인')).toBeInTheDocument();
  });

  it('uses unique input IDs when multiple modals are mounted', () => {
    render(
      <>
        <AuthModal isOpen={true} onClose={vi.fn()} onLogin={vi.fn()} />
        <AuthModal isOpen={true} onClose={vi.fn()} onLogin={vi.fn()} />
      </>,
    );

    const usernameInputs = screen.getAllByLabelText('사용자 이름');
    const ids = usernameInputs.map((input) => input.getAttribute('id'));
    expect(ids).toHaveLength(2);
    expect(ids.every(Boolean)).toBe(true);
    expect(new Set(ids).size).toBe(2);
  });
});
