import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ContestDetail } from './ContestDetail';
import { contestRequest, type Contest } from '../services/contestApi';
import { setAuthToken } from '../services/authIdentity';

vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(),
  contestRequest: vi.fn(),
}));

const contest: Contest = {
  id: 'floating-test', title: '알림 검증 대회', description: '규칙',
  published: true, startsAt: '2030-01-01T01:00:00Z', endsAt: '2030-01-01T03:00:00Z',
  serverTime: '2030-01-01T00:00:00Z', state: 'upcoming',
  joined: false, canManage: false, participantCount: 0, problems: [],
};
const message = '상단 로그인 버튼으로 로그인한 후 참가하세요.';

async function showPage() {
  await act(async () => {
    render(<MemoryRouter initialEntries={['/contests/floating-test']}><Routes>
      <Route path="/contests/:contestId" element={<ContestDetail />} />
      <Route path="/contests" element={<p>목록으로 이동함</p>} />
    </Routes></MemoryRouter>);
  });
}
async function join() {
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '참가 신청' })));
}
async function advance(ms: number) {
  await act(async () => { vi.advanceTimersByTime(ms); });
}

describe('floating contest notifications', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    localStorage.clear();
    setAuthToken(null);
    vi.mocked(contestRequest).mockImplementation(async path => {
      if (path?.endsWith('/join')) throw new Error('인증 필요');
      if (path?.endsWith('/scoreboard')) return { rows: [], problems: [], pendingCount: 0, state: 'upcoming' } as never;
      if (path?.includes('/submissions')) return { submissions: [], total: 0 } as never;
      return contest as never;
    });
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); localStorage.clear(); setAuthToken(null); });

  it('renders join feedback outside the page, without an inline error banner', async () => {
    await showPage();
    await join();
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(screen.getByTestId('contest-detail-page')).not.toContainElement(alert);
    expect(document.querySelector('.contest-error')).toBeNull();
    expect(screen.getByRole('heading', { name: contest.title })).toBeInTheDocument();
  });

  it('survives the five-second background refresh and dismisses at six seconds', async () => {
    await showPage();
    await join();
    await advance(5000);
    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(vi.mocked(contestRequest).mock.calls.filter(([path]) => path === '/floating-test')).toHaveLength(2);
    await advance(1000);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('restarts dismissal for repeated identical failures', async () => {
    await showPage();
    await join();
    await advance(4000);
    await join();
    await advance(2000);
    expect(screen.getByRole('alert')).toHaveTextContent(message);
    await advance(4000);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('supports explicit dismissal without removing the contest content', async () => {
    await showPage();
    await join();
    fireEvent.click(screen.getByRole('button', { name: '알림 닫기' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await advance(5000);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: contest.title })).toBeInTheDocument();
  });

  it('cleans up the portal when navigating away', async () => {
    await showPage();
    await join();
    await act(async () => fireEvent.click(screen.getByRole('link', { name: '콘테스트 목록' })));
    expect(screen.getByText('목록으로 이동함')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await advance(10000);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('drops account-scoped notices immediately on identity change', async () => {
    setAuthToken('first-account');
    await showPage();
    await join();
    expect(screen.getByRole('alert')).toHaveTextContent('인증 필요');
    vi.mocked(contestRequest).mockImplementation(() => new Promise(() => {}));
    act(() => setAuthToken('second-account'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByText(contest.title)).not.toBeInTheDocument();
  });

  it('keeps load failures outside the layout and shows a nonblank fallback', async () => {
    vi.mocked(contestRequest).mockRejectedValue(new Error('서버에 연결할 수 없습니다.'));
    await showPage();
    expect(screen.getByRole('alert')).toHaveTextContent('서버에 연결할 수 없습니다.');
    expect(screen.getByText('대회를 불러오지 못했습니다')).toBeInTheDocument();
    expect(screen.getByTestId('contest-detail-page')).not.toContainElement(screen.getByRole('alert'));
    await advance(7000);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});
