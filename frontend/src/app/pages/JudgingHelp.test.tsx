import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { JudgingHelp } from './JudgingHelp';
import { getProblem } from '../services/problemApi';
import { contestRequest } from '../services/contestApi';
import type { JudgePolicyLanguage, JudgePolicyLanguageLimits, PublicJudgeLimits } from '../services/judgePolicyTypes';

const mocks = vi.hoisted(() => ({
  getProblem: vi.fn(),
  contestRequest: vi.fn(),
}));

vi.mock('../services/problemApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/problemApi')>(),
  getProblem: mocks.getProblem,
}));

vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(),
  contestRequest: mocks.contestRequest,
}));

function limits(runtimeVersion: string, cpuMs: number, memoryBytes = 256 * 1024 ** 2): JudgePolicyLanguageLimits {
  return {
    runtimeVersion,
    compile: {
      cpuMs: cpuMs * 2,
      wallMs: cpuMs * 3,
      memoryBytes,
      outputBytes: 1024 ** 2,
      pids: 64,
      tmpBytes: 512 * 1024,
    },
    run: {
      cpuMs,
      wallMs: cpuMs + 250,
      memoryBytes,
      outputBytes: 1024 ** 2,
      pids: 64,
      tmpBytes: 512 * 1024,
    },
  };
}

const judgeLimits: PublicJudgeLimits = {
  policyId: 'help-policy',
  revision: 7,
  reviewStatus: 'verified',
  languages: Object.fromEntries([
    ['bpp', limits('B++ runtime 1.0', 1250)],
    ['python', limits('CPython 3.13', 2500, 512 * 1024 ** 2)],
    ['java', limits('OpenJDK 21', 1750)],
  ]) as Record<JudgePolicyLanguage, JudgePolicyLanguageLimits>,
};

const problem = {
  id: 'problem/42',
  title: '도움말 문제',
  judgeLimits,
  judgePolicyLegacy: false,
  judgePolicyCompatibility: false,
};

const contestProblem = {
  id: 'cp/7',
  problemId: 'problem/42',
  label: 'A',
  title: '대회 도움말 문제',
  points: 100,
  difficulty: 'iron5',
  description: '설명',
  tags: [],
  testCases: [],
  contest: {},
  judgeLimits,
  judgePolicyLegacy: false,
  judgePolicyCompatibility: true,
};

function renderHelp(initialEntry = '/help/judging') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <JudgingHelp />
    </MemoryRouter>,
  );
}

describe('JudgingHelp', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the generic FAQ without making a private API request', () => {
    renderHelp();

    expect(screen.getByRole('heading', { name: '도움말·FAQ' })).toBeInTheDocument();
    for (const question of [
      '채점은 어떻게 진행되나요?',
      '시간 제한은 어떻게 계산하나요?',
      '언어마다 제한이 다른 이유는 무엇인가요?',
      '메모리·출력·프로세스 제한은 무엇인가요?',
      '기존 문제 호환 정책은 무엇인가요?',
    ]) {
      expect(screen.getByText(question)).toBeInTheDocument();
    }
    expect(getProblem).not.toHaveBeenCalled();
    expect(contestRequest).not.toHaveBeenCalled();
  });

  it('loads public problem limits, selects the query language, and encodes the return link', async () => {
    mocks.getProblem.mockResolvedValue(problem);
    renderHelp('/help/judging?problem=problem%2F42&language=python');

    expect(await screen.findByRole('heading', { name: '이 문제의 채점 제한' })).toBeInTheDocument();
    await waitFor(() => expect(mocks.getProblem).toHaveBeenCalledWith('problem/42', expect.any(AbortSignal)));
    expect(screen.getByText('도움말 문제')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '언어' })).toHaveValue('python');
    expect(screen.getByRole('heading', { name: '채점 제한' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: '언어별 채점 제한' })).toBeInTheDocument();
    expect(screen.getByText('런타임 CPython 3.13')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '문제로 돌아가기' })).toHaveAttribute('href', '/problems/problem%2F42');

    fireEvent.change(screen.getByRole('combobox', { name: '언어' }), { target: { value: 'java' } });
    expect(screen.getByText('런타임 OpenJDK 21')).toBeInTheDocument();
  });

  it('uses the contest problem endpoint and keeps contest context in the return link', async () => {
    mocks.contestRequest.mockResolvedValue(contestProblem);
    renderHelp('/help/judging?contest=contest-7&problem=cp-7&language=java');

    expect(await screen.findByText('대회 도움말 문제')).toBeInTheDocument();
    await waitFor(() => expect(mocks.contestRequest).toHaveBeenCalledWith(
      '/contest-7/problems/cp-7',
      'GET',
      undefined,
      expect.any(AbortSignal),
    ));
    expect(getProblem).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: '문제로 돌아가기' })).toHaveAttribute(
      'href',
      '/contests/contest-7/problems/cp-7',
    );
    expect(screen.getByRole('combobox', { name: '언어' })).toHaveValue('java');
    expect(screen.getByText('런타임 OpenJDK 21')).toBeInTheDocument();
  });

  it('shows an error without inventing limits when the contextual request fails', async () => {
    mocks.getProblem.mockRejectedValue(new Error('private problem'));
    renderHelp('/help/judging?problem=private-problem&language=python');

    expect(await screen.findByRole('alert')).toHaveTextContent('문제의 채점 제한을 불러올 수 없습니다.');
    expect(screen.queryByRole('table', { name: '언어별 채점 제한' })).not.toBeInTheDocument();
    expect(screen.queryByText('2.5초')).not.toBeInTheDocument();
    expect(screen.queryByText('채점 제한 정보가 없습니다.')).not.toBeInTheDocument();
  });

  it.each([
    '/help/judging?contest=contest-only',
    '/help/judging?contest=&problem=cp-7',
    '/help/judging?contest=contest-7&problem=cp-7&problem=other',
    '/help/judging?contest=contest-7&problem=%20cp-7',
  ])('does not make a private request for an incomplete or malformed contest query: %s', (entry) => {
    renderHelp(entry);

    expect(screen.getByRole('alert')).toHaveTextContent('문제 링크가 올바르지 않습니다.');
    expect(getProblem).not.toHaveBeenCalled();
    expect(contestRequest).not.toHaveBeenCalled();
  });

  it('encodes contest and problem identifiers in the contextual help link', async () => {
    mocks.contestRequest.mockResolvedValue(contestProblem);
    renderHelp('/help/judging?contest=contest%2F7&problem=cp%2F7&language=python');

    expect(await screen.findByText('대회 도움말 문제')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '문제로 돌아가기' })).toHaveAttribute(
      'href',
      '/contests/contest%2F7/problems/cp%2F7',
    );
    expect(mocks.contestRequest).toHaveBeenCalledWith(
      '/contest%2F7/problems/cp%2F7',
      'GET',
      undefined,
      expect.any(AbortSignal),
    );
  });
});
