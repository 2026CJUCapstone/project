import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Profile } from './Profile';
import { getCurrentUser } from '../services/authApi';
import { setAuthToken } from '../services/authIdentity';
import { ApiError } from '../services/apiBase';

vi.mock('../components/ProfileStatsPanel', () => ({ ProfileStatsPanel: ({ user }: { user: { name: string } }) => <p>Stats for {user.name}</p> }));
vi.mock('../components/AuthModal', () => ({ AuthModal: ({ isOpen }: { isOpen: boolean }) => isOpen ? <div role="dialog">Login</div> : null }));
vi.mock('../services/authApi', () => ({ getCurrentUser: vi.fn() }));
const user = { id: 'a', username: 'Alice', role: 'user', totalScore: 10 };
const mount = () => render(<MemoryRouter><Profile /></MemoryRouter>);

describe('profile overview', () => {
  beforeEach(() => { vi.resetAllMocks(); localStorage.clear(); localStorage.setItem('authToken', 'a-token'); vi.mocked(getCurrentUser).mockResolvedValue(user); });
  it('shows stats and an edit link, but no settings or form controls', async () => {
    mount();
    expect(await screen.findByText('Stats for Alice')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '프로필 편집' })).toHaveAttribute('href', '/settings');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '저장' })).not.toBeInTheDocument();
  });
  it('asks guests to log in and does not fetch a profile', () => {
    localStorage.removeItem('authToken'); mount();
    fireEvent.click(screen.getByRole('button', { name: '로그인하기' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '프로필 편집' })).not.toBeInTheDocument();
    expect(getCurrentUser).not.toHaveBeenCalled();
  });
  it('removes old stats on logout', async () => {
    mount(); await screen.findByText('Stats for Alice');
    act(() => setAuthToken(null));
    expect(screen.queryByText('Stats for Alice')).not.toBeInTheDocument();
  });
  it('ignores a late read after an account change', async () => {
    let resolve!: (value: typeof user) => void;
    vi.mocked(getCurrentUser).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    mount();
    vi.mocked(getCurrentUser).mockResolvedValue({ ...user, id: 'b', username: 'Bob' });
    act(() => setAuthToken('b-token'));
    await screen.findByText('Stats for Bob');
    await act(async () => resolve(user));
    expect(screen.queryByText('Stats for Alice')).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('b-compiler-user')!).name).toBe('Bob');
  });
  it('keeps a session on transient read failure and retries', async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new ApiError('unavailable', 503)); mount();
    await screen.findByRole('alert');
    expect(localStorage.getItem('authToken')).toBe('a-token');
    fireEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByText('Stats for Alice')).toBeInTheDocument();
  });
});
