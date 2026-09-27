import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ContestEditor } from './ContestEditor';
import { setAuthToken } from '../services/authIdentity';

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  contestPageRequest: vi.fn(),
  contestRequest: vi.fn(),
  navigate: vi.fn(),
  validationProps: vi.fn(),
}));

vi.mock('../services/authApi', () => ({ getCurrentUser: mocks.getCurrentUser }));
vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(),
  contestPageRequest: mocks.contestPageRequest,
  contestRequest: mocks.contestRequest,
}));
vi.mock('../components/ProblemAuthoringPanel', () => ({ ProblemAuthoringPanel: () => <div>출처 패널</div> }));
vi.mock('../components/JudgePolicyEditor', () => ({
  JudgePolicyEditor: ({ onReplace }: { onReplace: (value: null) => void }) => <button type="button" onClick={() => onReplace(null)}>정책 변경 테스트</button>,
}));
vi.mock('../components/ReferenceSolutionValidationPanel', () => ({
  ReferenceSolutionValidationPanel: (props: unknown) => {
    mocks.validationProps(props);
    return <div>기준 풀이 패널</div>;
  },
}));
vi.mock('react-router', async importOriginal => ({
  ...await importOriginal<typeof import('react-router')>(),
  useNavigate: () => mocks.navigate,
}));

const digest = (character: string) => `sha256:${character.repeat(64)}`;
const policy = {
  schemaVersion: 1 as const, policyId: 'verified-policy', revision: 1, reviewStatus: 'verified' as const,
  testSuiteHash: digest('a'), preparationCleanupMs: 1_000,
  profiles: {}, evidence: {},
};
const authoring = {
  problemId: 'problem-1', fingerprint: digest('b'), metadata: null,
  categories: { sources: 'pending' as const, statement: 'pending' as const, tests: 'pending' as const, resources: 'pending' as const }, events: [],
};

describe('ContestEditor authoring validation wiring', () => {
  beforeEach(() => {
    mocks.getCurrentUser.mockReset().mockResolvedValue({ role: 'admin' });
    mocks.contestPageRequest.mockReset().mockResolvedValue({ items: [], total: 0 });
    mocks.contestRequest.mockReset()
      .mockResolvedValueOnce({
        id: 'contest-1', title: '신입생 대회', description: '', startsAt: '2030-01-01T00:00:00Z', endsAt: '2030-01-02T00:00:00Z',
        serverTime: '2029-12-31T00:00:00Z', state: 'draft', published: false, joined: false, canManage: true, participantCount: 0,
        problems: [{
          contestProblemId: 'contest-problem-1', problemId: 'problem-1', points: 100,
          newProblem: { title: 'A 문제', description: '설명', difficulty: 'iron5', tags: [], points: 100, testCases: [{ input: '1', expectedOutput: '1' }], hiddenTestCases: [], judgePolicy: policy },
        }],
        authoring: { 'problem-1': authoring },
      })
      .mockResolvedValueOnce({ id: 'contest-1' });
    mocks.navigate.mockReset();
    mocks.validationProps.mockReset();
  });

  afterEach(() => setAuthToken(null));

  it('passes the persisted contest row to the private panel and strips it from the write body', async () => {
    render(<MemoryRouter initialEntries={['/contests/contest-1/edit']}><Routes><Route path="/contests/:contestId/edit" element={<ContestEditor />} /></Routes></MemoryRouter>);

    expect(await screen.findByText('기준 풀이 패널')).toBeInTheDocument();
    expect(mocks.validationProps).toHaveBeenLastCalledWith(expect.objectContaining({
      contestId: 'contest-1', contestProblemId: 'contest-problem-1', policy, authoring, isAdmin: true,
    }));

    fireEvent.click(screen.getByRole('button', { name: '정책 변경 테스트' }));
    expect(mocks.validationProps).toHaveBeenLastCalledWith(expect.objectContaining({
      contestProblemId: 'contest-problem-1', policy, authoring,
    }));

    fireEvent.submit(screen.getByRole('button', { name: '대회 저장' }).closest('form')!);
    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledTimes(2));
    const [, method, body] = mocks.contestRequest.mock.calls[1];
    expect(method).toBe('PUT');
    expect(body.problems[0]).toEqual(expect.objectContaining({ problemId: 'problem-1', points: 100 }));
    expect(body.problems[0]).not.toHaveProperty('contestProblemId');
  });
});
