import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../services/apiBase';
import { getCurrentUser, updateProfile } from '../services/authApi';
import { Header } from './Header';

vi.mock('./AuthModal', () => ({ AuthModal: () => null }));
vi.mock('./ProfileStatsPanel', () => ({ ProfileStatsPanel: () => null }));
vi.mock('./UserProfile', () => ({ UserProfile: ({ username, onOpenProfile }: { username: string; onOpenProfile: () => void }) => <button onClick={onOpenProfile}>{username}</button> }));
vi.mock('../services/authApi', () => ({ getCurrentUser: vi.fn(), updateProfile: vi.fn() }));
vi.mock('../services/projectApi', () => ({ saveCodeProject: vi.fn() }));
vi.mock('../store/compilerStore', () => ({
  useCompilerStore: () => ({
    theme: 'light', toggleTheme: vi.fn(), code: '', codeStorageScope: 'main', saveCode: vi.fn(), addOutput: vi.fn(),
    cancelRun: vi.fn(), isRunning: false, compile: vi.fn(), compileAndStartTerminal: vi.fn(), isCompiling: false,
    language: 'bpp', selectLanguage: vi.fn(), autoSaveEnabled: false, setAutoSaveEnabled: vi.fn(),
  }),
}));

describe('Header authentication refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem('authToken', 'still-valid-token');
    localStorage.setItem('b-compiler-user', JSON.stringify({ name: 'saved-user', avatar: '' }));
  });

  it('keeps a saved session after a transient error and lets the user retry', async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new ApiError('service unavailable', 503));
    vi.mocked(getCurrentUser).mockResolvedValueOnce({
      id: 'u1', username: 'fresh-user', role: 'user', totalScore: 0,
    });

    render(<MemoryRouter><Header /></MemoryRouter>);

    expect(await screen.findByRole('status')).toHaveTextContent('로그인 정보를 확인하지 못했습니다');
    expect(localStorage.getItem('authToken')).toBe('still-valid-token');
    expect(screen.getByText('saved-user')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
    expect(localStorage.getItem('authToken')).toBe('still-valid-token');
    expect(screen.getByText('fresh-user')).toBeInTheDocument();
  });

  it('does not fill cleared edit fields with display-name or avatar fallbacks', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      id: 'u2', username: 'raw-profile-user', role: 'user', totalScore: 0,
      nickname: null, email: null, avatarUrl: null,
    });
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'raw-profile-user' }));
    expect(await screen.findByLabelText('닉네임')).toHaveValue('');
    expect(screen.getByLabelText('이메일')).toHaveValue('');
    expect(screen.getByLabelText('아바타 URL')).toHaveValue('');
  });

  it('preserves a typed draft when the profile refresh resolves late', async () => {
    const original = { id: 'u3', username: 'draft-user', role: 'user', totalScore: 0,
      email: 'original@example.test', nickname: null, avatarUrl: null };
    let resolveRefresh!: (value: typeof original) => void;
    vi.mocked(getCurrentUser).mockResolvedValueOnce(original).mockImplementationOnce(
      () => new Promise(resolve => { resolveRefresh = resolve; }),
    );
    vi.mocked(updateProfile).mockResolvedValue({ ...original, email: 'typed@example.test' });
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'draft-user' }));
    fireEvent.change(await screen.findByLabelText('이메일'), { target: { value: 'typed@example.test' } });
    await act(async () => resolveRefresh(original));
    expect(screen.getByLabelText('이메일')).toHaveValue('typed@example.test');
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(updateProfile).toHaveBeenCalledWith({
      email: 'typed@example.test', nickname: null, avatarUrl: null,
    }));
  });

  it('does not overwrite a saved profile with an older in-flight profile read', async () => {
    const original = { id: 'u4', username: 'saved-draft-user', role: 'user', totalScore: 0,
      email: 'original@example.test', nickname: null, avatarUrl: null };
    let resolveRefresh!: (value: typeof original) => void;
    vi.mocked(getCurrentUser).mockResolvedValueOnce(original).mockImplementationOnce(
      () => new Promise(resolve => { resolveRefresh = resolve; }),
    );
    vi.mocked(updateProfile).mockResolvedValue({ ...original, email: 'saved@example.test' });
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'saved-draft-user' }));
    fireEvent.change(await screen.findByLabelText('이메일'), { target: { value: 'saved@example.test' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    await waitFor(() => expect(screen.queryByRole('heading', { name: '내 프로필' })).not.toBeInTheDocument());
    await act(async () => resolveRefresh(original));
    expect(JSON.parse(localStorage.getItem('b-compiler-user')!)).toMatchObject({ email: 'saved@example.test' });
  });

  it('closes the old profile editor and refreshes identity after another tab changes account', async () => {
    const first = { id: 'a', username: 'account-a', role: 'user', totalScore: 0, email: 'a@example.test' };
    const second = { id: 'b', username: 'account-b', role: 'user', totalScore: 0, email: 'b@example.test' };
    vi.mocked(getCurrentUser).mockResolvedValue(first);
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'account-a' }));
    fireEvent.change(await screen.findByLabelText('이메일'), { target: { value: 'a-draft@example.test' } });
    await act(async () => {});
    vi.mocked(getCurrentUser).mockResolvedValue(second);
    act(() => {
      localStorage.setItem('authToken', 'account-b-token');
      window.dispatchEvent(new StorageEvent('storage', { key: 'authToken', newValue: 'account-b-token' }));
    });
    await waitFor(() => expect(screen.queryByRole('heading', { name: '내 프로필' })).not.toBeInTheDocument());
    expect(await screen.findByRole('button', { name: 'account-b' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'account-a' })).not.toBeInTheDocument();
    expect(updateProfile).not.toHaveBeenCalled();
  });

  it('does not submit an old profile draft with a different current token before storage notification', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      id: 'a', username: 'account-a', role: 'user', totalScore: 0, email: 'a@example.test',
    });
    render(<MemoryRouter><Header /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'account-a' }));
    fireEvent.change(await screen.findByLabelText('이메일'), { target: { value: 'a-draft@example.test' } });
    localStorage.setItem('authToken', 'account-b-token');
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(updateProfile).not.toHaveBeenCalled();
  });

  it('does not present a cached account as logged in when no token exists', async () => {
    localStorage.removeItem('authToken');
    render(<MemoryRouter><Header /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: 'saved-user' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '로그인' })).toBeInTheDocument();
    expect(getCurrentUser).not.toHaveBeenCalled();
  });

  it('refuses to open the previous account profile before its storage event is delivered', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ id: 'a', username: 'account-a', role: 'user', totalScore: 0 });
    render(<MemoryRouter><Header /></MemoryRouter>);
    await screen.findByRole('button', { name: 'account-a' });
    localStorage.setItem('authToken', 'account-b-token');
    fireEvent.click(screen.getByRole('button', { name: 'account-a' }));
    expect(screen.queryByRole('heading', { name: '내 프로필' })).not.toBeInTheDocument();
  });
});
