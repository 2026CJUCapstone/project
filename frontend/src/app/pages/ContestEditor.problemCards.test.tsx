import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ContestEditor } from './ContestEditor';

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  contestPageRequest: vi.fn(),
  contestRequest: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock('../services/authApi', () => ({ getCurrentUser: mocks.getCurrentUser }));
vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(),
  contestPageRequest: mocks.contestPageRequest,
  contestRequest: mocks.contestRequest,
}));
vi.mock('../components/ProblemAuthoringPanel', () => ({ ProblemAuthoringPanel: () => <div>출처 패널</div> }));
vi.mock('../components/JudgePolicyEditor', () => ({ JudgePolicyEditor: () => <div>정책 패널</div> }));
vi.mock('../components/ReferenceSolutionValidationPanel', () => ({ ReferenceSolutionValidationPanel: () => <div>검증 패널</div> }));
vi.mock('react-router', async importOriginal => ({
  ...await importOriginal<typeof import('react-router')>(),
  useNavigate: () => mocks.navigate,
}));

const problem = (title: string, points: number) => ({
  points,
  newProblem: {
    title,
    description: `${title} 설명`,
    difficulty: 'bronze5',
    tags: ['입출력'],
    points,
    testCases: [{ input: '1', expectedOutput: '1' }],
    hiddenTestCases: [{ input: '2', expectedOutput: '2' }],
  },
});

describe('ContestEditor problem cards', () => {
  beforeEach(() => {
    mocks.getCurrentUser.mockReset().mockResolvedValue({ role: 'admin' });
    mocks.contestPageRequest.mockReset().mockResolvedValue({ items: [], total: 0 });
    mocks.contestRequest.mockReset()
      .mockResolvedValueOnce({
        id: 'contest-1', title: '카드 대회', description: '', startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-02T00:00:00Z',
        serverTime: '2029-12-31T00:00:00Z', state: 'draft', published: false, joined: false, canManage: true, participantCount: 0,
        problems: [problem('첫 번째 문제', 100), problem('두 번째 문제', 200)],
        authoring: {},
      })
      .mockResolvedValueOnce({ id: 'contest-1' });
    mocks.navigate.mockReset();
  });

  it('shows compact cards and edits only the selected problem', async () => {
    render(<MemoryRouter initialEntries={['/contests/contest-1/edit']}><Routes><Route path="/contests/:contestId/edit" element={<ContestEditor />} /></Routes></MemoryRouter>);

    const firstCard = await screen.findByRole('button', { name: 'A 첫 번째 문제 편집' });
    expect(screen.getByRole('button', { name: 'B 두 번째 문제 편집' })).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: '문제 제목' })).not.toBeInTheDocument();

    fireEvent.click(firstCard);
    const title = screen.getByRole('textbox', { name: '문제 제목' });
    expect(title).toHaveValue('첫 번째 문제');
    expect(screen.queryByText('두 번째 문제 설명')).not.toBeInTheDocument();
    fireEvent.change(title, { target: { value: '수정한 첫 문제' } });
    fireEvent.click(screen.getByRole('button', { name: '← 문제 목록' }));

    expect(screen.getByRole('button', { name: 'A 수정한 첫 문제 편집' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'B 두 번째 문제 편집' }));
    expect(screen.getByRole('textbox', { name: '문제 제목' })).toHaveValue('두 번째 문제');
  });

  it('keeps card order actions and submits every edited problem', async () => {
    render(<MemoryRouter initialEntries={['/contests/contest-1/edit']}><Routes><Route path="/contests/:contestId/edit" element={<ContestEditor />} /></Routes></MemoryRouter>);

    await screen.findByRole('button', { name: 'A 첫 번째 문제 편집' });
    fireEvent.click(screen.getByRole('button', { name: 'B 위로 이동' }));
    expect(screen.getByRole('button', { name: 'A 두 번째 문제 편집' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'B 첫 번째 문제 편집' })).toBeInTheDocument();

    fireEvent.submit(screen.getByRole('button', { name: '대회 저장' }).closest('form')!);
    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledTimes(2));
    expect(mocks.contestRequest.mock.calls[1][2].problems.map((item: { newProblem: { title: string } }) => item.newProblem.title)).toEqual(['두 번째 문제', '첫 번째 문제']);
  });

  it('opens a newly added problem immediately and returns to an updated card', async () => {
    mocks.contestRequest.mockReset().mockResolvedValue({ id: 'created-contest' });
    render(<MemoryRouter initialEntries={['/contests/new']}><Routes><Route path="/contests/new" element={<ContestEditor />} /></Routes></MemoryRouter>);

    await screen.findByRole('heading', { name: '대회 만들기' });
    fireEvent.click(screen.getByRole('button', { name: '신규 문제 추가' }));
    const title = screen.getByRole('textbox', { name: '문제 제목' });
    fireEvent.change(title, { target: { value: '새 카드 문제' } });
    fireEvent.click(screen.getByRole('button', { name: '← 문제 목록' }));
    expect(screen.getByRole('button', { name: 'A 새 카드 문제 편집' })).toBeInTheDocument();
  });
});
