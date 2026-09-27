import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Settings } from './Settings';
import { getCurrentUser, updateProfile } from '../services/authApi';
import { ApiError } from '../services/apiBase';
import { setAuthToken } from '../services/authIdentity';

vi.mock('../components/ProfileStatsPanel', () => ({ ProfileStatsPanel: () => <p>Stats</p> }));
vi.mock('../components/AuthModal', () => ({ AuthModal: ({ isOpen }: { isOpen: boolean }) => isOpen ? <div role="dialog">Login</div> : null }));
vi.mock('../services/authApi', () => ({ getCurrentUser: vi.fn(), updateProfile: vi.fn() }));
vi.mock('../store/compilerStore', () => ({ useCompilerStore: () => ({ autoSaveEnabled: false, setAutoSaveEnabled: vi.fn() }) }));

const user = { id: 'a', username: 'account-a', nickname: 'Alice', email: 'a@example.test', avatarUrl: null, role: 'user', totalScore: 12 };
const mount = () => render(<MemoryRouter initialEntries={['/settings']}><Settings /></MemoryRouter>);

describe('settings profile editor', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    localStorage.clear();
    localStorage.setItem('authToken', 'a-token');
    vi.mocked(getCurrentUser).mockResolvedValue(user);
  });

  it('requires login on direct navigation without exposing a cached account', () => {
    localStorage.removeItem('authToken');
    localStorage.setItem('b-compiler-user', JSON.stringify(user));
    mount();
    expect(screen.getByRole('heading', { level: 1, name: '설정' })).toBeInTheDocument();
    expect(screen.queryByLabelText('이메일')).not.toBeInTheDocument();
    expect(getCurrentUser).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '로그인하기' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('retains the page after save, publishes new values, and supports clearing', async () => {
    vi.mocked(updateProfile).mockResolvedValue({ ...user, nickname: null, email: null });
    mount();
    fireEvent.change(await screen.findByLabelText('닉네임'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('이메일'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(await screen.findByText('프로필을 저장했습니다.')).toBeInTheDocument();
    expect(updateProfile).toHaveBeenCalledWith({ nickname: null, email: null, avatarUrl: null });
    expect(screen.getByRole('heading', { name: '설정' })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('b-compiler-user')!)).toMatchObject({ nickname: null, email: null });
  });

  it('cancels draft edits without leaving the page or writing', async () => {
    mount();
    fireEvent.change(await screen.findByLabelText('닉네임'), { target: { value: 'Draft' } });
    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(screen.getByLabelText('닉네임')).toHaveValue('Alice');
    expect(updateProfile).not.toHaveBeenCalled();
  });

  it('offers retry on transient read failure without removing the token', async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new ApiError('unavailable', 503));
    mount();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(localStorage.getItem('authToken')).toBe('a-token');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByLabelText('닉네임')).toHaveValue('Alice');
  });

  it('discards unauthorized sessions on read', async () => {
    vi.mocked(getCurrentUser).mockRejectedValue(new ApiError('unauthorized', 401));
    mount();
    expect(await screen.findByRole('button', { name: '로그인하기' })).toBeInTheDocument();
    expect(localStorage.getItem('authToken')).toBeNull();
  });

  it('keeps the draft on save failure and allows retry', async () => {
    vi.mocked(updateProfile).mockRejectedValueOnce(new ApiError('duplicate nickname', 409));
    mount();
    fireEvent.change(await screen.findByLabelText('닉네임'), { target: { value: 'New name' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('duplicate nickname');
    expect(screen.getByLabelText('닉네임')).toHaveValue('New name');
    expect(screen.getByRole('button', { name: '저장' })).toBeEnabled();
  });

  it('does not restore a completed save after logout', async () => {
    let resolveSave!: (value: typeof user) => void;
    vi.mocked(updateProfile).mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
    mount();
    await screen.findByLabelText('닉네임');
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    act(() => { setAuthToken(null); localStorage.removeItem('b-compiler-user'); });
    await act(async () => resolveSave({ ...user, nickname: 'Late' }));
    expect(screen.getByRole('button', { name: '로그인하기' })).toBeInTheDocument();
    expect(localStorage.getItem('b-compiler-user')).toBeNull();
  });

  it('does not publish a late save after navigation unmounts the page', async () => {
    let resolveSave!: (value: typeof user) => void;
    vi.mocked(updateProfile).mockImplementation(() => new Promise(resolve => { resolveSave = resolve; }));
    const view = mount();
    await screen.findByLabelText('닉네임');
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    view.unmount();
    await act(async () => resolveSave({ ...user, nickname: 'Late' }));
    expect(JSON.parse(localStorage.getItem('b-compiler-user')!).nickname).toBe('Alice');
  });

  it('discards a previous account read when a new account takes over', async () => {
    let resolveRead!: (value: typeof user) => void;
    vi.mocked(getCurrentUser).mockImplementationOnce(() => new Promise(resolve => { resolveRead = resolve; }));
    mount();
    vi.mocked(getCurrentUser).mockResolvedValue({ ...user, id: 'b', nickname: 'Bob' });
    act(() => setAuthToken('b-token'));
    expect(await screen.findByLabelText('닉네임')).toHaveValue('Bob');
    await act(async () => resolveRead(user));
    await waitFor(() => expect(screen.getByLabelText('닉네임')).toHaveValue('Bob'));
  });
});
