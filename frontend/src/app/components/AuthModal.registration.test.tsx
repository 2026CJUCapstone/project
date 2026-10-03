import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AuthModal } from './AuthModal';
import { getCurrentUser, login, register } from '../services/authApi';

vi.mock('../services/authApi', () => ({
  getCurrentUser: vi.fn(),
  login: vi.fn(),
  register: vi.fn(),
  confirmPasswordReset: vi.fn(),
  requestPasswordReset: vi.fn(),
}));

afterEach(cleanup);
beforeEach(() => {
  localStorage.clear();
  vi.resetAllMocks();
});

function openRegistration() {
  render(<AuthModal isOpen={true} onClose={vi.fn()} onLogin={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: '회원가입' }));
}

function fillRegistration({
  username = 'cuha_student',
  email = 'student@example.com',
  nickname,
  password = 'fixture-password',
}: {
  username?: string;
  email?: string;
  nickname: string;
  password?: string;
}) {
  fireEvent.change(screen.getByLabelText('사용자 이름'), { target: { value: username } });
  fireEvent.change(screen.getByLabelText('이메일'), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/표시 이름\s+\(실명\)/), { target: { value: nickname } });
  fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: password } });
  fireEvent.change(screen.getByLabelText('비밀번호 확인'), { target: { value: password } });
}

function submitRegistration() {
  const form = screen.getByRole('button', { name: '계정 생성' }).closest('form');
  if (!form) throw new Error('registration form was not rendered');
  fireEvent.submit(form);
}

it.each(['', ' \u3000\t\n '])('rejects a blank real name before calling the registration API (%j)', async nickname => {
  openRegistration();
  fillRegistration({ nickname });
  submitRegistration();

  await waitFor(() => expect(screen.getByText('표시 이름에 본인의 실명을 입력해 주세요.')).toBeInTheDocument());
  expect(register).not.toHaveBeenCalled();
  expect(login).not.toHaveBeenCalled();
});

it('trims Unicode surrounding whitespace and continues through the login flow', async () => {
  const onClose = vi.fn();
  const onLogin = vi.fn();
  vi.mocked(register).mockResolvedValue(undefined);
  vi.mocked(login).mockResolvedValue({ accessToken: 'student-token', tokenType: 'bearer' });
  vi.mocked(getCurrentUser).mockResolvedValue({
    id: 'student-id',
    username: 'cuha_student',
    email: 'student@example.com',
    nickname: '김민수',
    role: 'user',
    totalScore: 0,
  });

  render(<AuthModal isOpen={true} onClose={onClose} onLogin={onLogin} />);
  fireEvent.click(screen.getByRole('button', { name: '회원가입' }));
  fillRegistration({
    username: '  cuha_student  ',
    email: ' Student@Example.COM ',
    nickname: ' \u3000김민수\u2003 ',
  });
  submitRegistration();

  await waitFor(() => {
    expect(register).toHaveBeenCalledWith(
      'cuha_student',
      'student@example.com',
      'fixture-password',
      '김민수',
    );
  });
  await waitFor(() => expect(login).toHaveBeenCalledWith('cuha_student', 'fixture-password'));
  await waitFor(() => expect(onLogin).toHaveBeenCalledTimes(1));
  expect(getCurrentUser).toHaveBeenCalledTimes(1);
  expect(localStorage.getItem('authToken')).toBe('student-token');
  expect(onClose).toHaveBeenCalledTimes(1);
});

it('preserves Unicode login identities instead of stripping their script', async () => {
  vi.mocked(login).mockResolvedValue({ accessToken: 'unicode-token', tokenType: 'bearer' });
  vi.mocked(getCurrentUser).mockResolvedValue({
    id: 'unicode-id',
    username: '두글',
    role: 'user',
    totalScore: 0,
  });

  render(<AuthModal isOpen={true} onClose={vi.fn()} onLogin={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('사용자 이름'), { target: { value: '두글' } });
  fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'fixture-password' } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));

  await waitFor(() => expect(login).toHaveBeenCalledWith('두글', 'fixture-password'));
});
