import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import type { Problem } from '../services/problemApi';
import type { ProblemAuthoringRecord } from '../services/problemAuthoringApi';
import type { JudgePolicy } from '../services/judgePolicyTypes';
import { Admin } from './Admin';

const mocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  getProblems: vi.fn(),
  createProblem: vi.fn(),
  deleteProblem: vi.fn(),
  updateProblem: vi.fn(),
  publishProblem: vi.fn(),
  getAdminUsers: vi.fn(),
  updateAdminUser: vi.fn(),
  validationProps: vi.fn(),
  problem: null as unknown,
  authoringRecord: {
    problemId: 'problem-1',
    fingerprint: 'problem-fingerprint',
    metadata: {
      sources: [{ url: 'https://example.test/source', title: 'Test source' }],
      adaptationNotes: 'Adapted for the course',
      assets: [{ role: 'reference', name: 'solution.py', digest: `sha256:${'a'.repeat(64)}`, language: 'python' }],
      requiredLanguages: ['python'],
    },
    categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' },
    events: [],
  },
}));

vi.mock('../services/authApi', () => ({ getCurrentUser: mocks.getCurrentUser }));
vi.mock('../services/problemApi', () => ({
  getProblems: mocks.getProblems,
  createProblem: mocks.createProblem,
  deleteProblem: mocks.deleteProblem,
  updateProblem: mocks.updateProblem,
  publishProblem: mocks.publishProblem,
}));
vi.mock('../services/adminApi', () => ({ getAdminUsers: mocks.getAdminUsers, updateAdminUser: mocks.updateAdminUser }));
vi.mock('../components/ProblemAuthoringPanel', () => ({
  ProblemAuthoringPanel: ({ problemId, onRecordChange }: { problemId: string; onRecordChange?: (record: ProblemAuthoringRecord) => void }) => (
    <button type="button" onClick={() => onRecordChange?.(mocks.authoringRecord as ProblemAuthoringRecord)}>검수 정보 로드 {problemId}</button>
  ),
}));
vi.mock('../components/ReferenceSolutionValidationPanel', () => ({
  ReferenceSolutionValidationPanel: (props: unknown) => {
    mocks.validationProps(props);
    return <div>기준 풀이 검증 패널</div>;
  },
}));
vi.mock('recharts', () => ({
  PieChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Pie: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Cell: () => null,
  Tooltip: () => null,
  Legend: () => null,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const policy = {
  schemaVersion: 1,
  policyId: 'publication-policy',
  revision: 1,
  reviewStatus: 'verified',
  testSuiteHash: `sha256:${'b'.repeat(64)}`,
  profiles: {},
  preparationCleanupMs: 1_000,
} as JudgePolicy;

function draftProblem(): Problem {
  return {
    id: 'problem-1', title: 'Publication draft', difficulty: 'iron5', tags: [], description: 'Description', points: 100,
    testCases: [], hiddenTestCases: [], createdAt: '2030-01-01T00:00:00Z', solved: false, attempted: false,
    bestAwardedPoints: 0, publicationStatus: 'draft', judgePolicy: policy,
  };
}

describe('Admin problem publication flow', () => {
  beforeEach(() => {
    localStorage.setItem('authToken', 'admin-token');
    mocks.problem = draftProblem();
    mocks.getCurrentUser.mockReset().mockResolvedValue({ id: 'admin-1', username: 'admin', role: 'admin' });
    mocks.getProblems.mockReset().mockImplementation(async () => [mocks.problem]);
    mocks.createProblem.mockReset();
    mocks.deleteProblem.mockReset();
    mocks.updateProblem.mockReset();
    mocks.publishProblem.mockReset().mockImplementation(async () => {
      mocks.problem = { ...(mocks.problem as Problem), publicationStatus: 'published' };
      return mocks.problem;
    });
    mocks.getAdminUsers.mockReset().mockResolvedValue({ users: [], total: 0, filteredTotal: 0 });
    mocks.updateAdminUser.mockReset();
    mocks.validationProps.mockReset();
  });

  afterEach(() => localStorage.clear());

  it('shows publication status, wires standalone review and publishes then refreshes the problem list', async () => {
    render(<MemoryRouter><Admin /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '문제 관리' }));

    expect(await screen.findByText('초안')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검수' }));
    expect(await screen.findByText('기준 풀이 검증 패널')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '검수 정보 로드 problem-1' }));

    await waitFor(() => expect(mocks.validationProps).toHaveBeenLastCalledWith(expect.objectContaining({
      problemId: 'problem-1', policy, authoring: mocks.authoringRecord, isAdmin: true,
    })));
    fireEvent.click(screen.getByRole('button', { name: '공개' }));
    await waitFor(() => expect(mocks.publishProblem).toHaveBeenCalledWith('problem-1'));
    expect(await screen.findByText('공개')).toBeInTheDocument();
    expect(mocks.getProblems).toHaveBeenCalledTimes(2);
  });
});
