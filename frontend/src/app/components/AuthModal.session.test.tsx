import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { AuthModal } from './AuthModal';
import { getCurrentUser, login } from '../services/authApi';
import { setAuthToken } from '../services/authIdentity';

vi.mock('../services/authApi', () => ({
  getCurrentUser: vi.fn(), login: vi.fn(), register: vi.fn(),
  confirmPasswordReset: vi.fn(), requestPasswordReset: vi.fn(),
}));
beforeEach(() => { localStorage.clear(); vi.resetAllMocks(); });

function submit(onLogin: () => void, identity = 'account-a') {
  render(<AuthModal isOpen onClose={vi.fn()} onLogin={onLogin} />);
  fireEvent.change(screen.getByLabelText('사용자 이름'), { target: { value: identity } });
  fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'fixture-password' } });
  fireEvent.click(screen.getByRole('button', { name: '로그인' }));
}

it('does not replace a newer session when an earlier login response arrives', async () => {
  let finish!: (value: Awaited<ReturnType<typeof login>>) => void;
  vi.mocked(login).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const onLogin = vi.fn(); submit(onLogin);
  act(() => setAuthToken('account-b-token'));
  await act(async () => finish({ accessToken: 'account-a-token', tokenType: 'bearer' }));
  expect(localStorage.getItem('authToken')).toBe('account-b-token');
  expect(getCurrentUser).not.toHaveBeenCalled();
  expect(onLogin).not.toHaveBeenCalled();
});

it('does not publish an old profile after logout during the login profile read', async () => {
  vi.mocked(login).mockResolvedValue({ accessToken: 'account-a-token', tokenType: 'bearer' });
  let finish!: (value: Awaited<ReturnType<typeof getCurrentUser>>) => void;
  vi.mocked(getCurrentUser).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const onLogin = vi.fn(); submit(onLogin);
  await waitFor(() => expect(getCurrentUser).toHaveBeenCalled());
  act(() => setAuthToken(null));
  await act(async () => finish({ id: 'a', username: 'account-a', role: 'user', totalScore: 0 }));
  expect(onLogin).not.toHaveBeenCalled();
  expect(localStorage.getItem('authToken')).toBeNull();
});

it.each(['두글', `${'long-mail-'.repeat(6)}user@example.test`])('accepts the complete supported login identity %s', async identity => {
  vi.mocked(login).mockResolvedValue({ accessToken: 'account-a-token', tokenType: 'bearer' });
  vi.mocked(getCurrentUser).mockResolvedValue({ id: 'a', username: 'account-a', role: 'user', totalScore: 0 });
  const onLogin = vi.fn(); submit(onLogin, identity);
  await waitFor(() => expect(login).toHaveBeenCalledWith(identity, 'fixture-password'));
  await waitFor(() => expect(onLogin).toHaveBeenCalled());
});
