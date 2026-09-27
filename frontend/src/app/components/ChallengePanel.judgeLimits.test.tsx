import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ChallengePanel } from './ChallengePanel';
import { useCompilerStore } from '../store/compilerStore';
import type { Contest } from '../services/contestApi';
import type { JudgePolicyLanguageLimits, PublicJudgeLimits } from '../services/judgePolicyTypes';

vi.mock('./ProblemReviewControls', () => ({ ProblemReviewControls: () => <div>review controls</div> }));

const initialStore = useCompilerStore.getState();

function limits(runtimeVersion: string, cpuMs: number): JudgePolicyLanguageLimits {
  return {
    runtimeVersion,
    compile: { cpuMs: cpuMs * 2, wallMs: cpuMs * 3, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
    run: { cpuMs, wallMs: cpuMs + 250, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
  };
}

const policy: PublicJudgeLimits = {
  policyId: 'freshman-2026',
  revision: 4,
  reviewStatus: 'verified',
  languages: {
    bpp: limits('B++ 1.0', 1250),
    python: limits('CPython 3.13', 2750),
    java: limits('OpenJDK 21', 3500),
  },
};

interface PanelChallenge {
  id: string;
  title: string;
  difficulty: string;
  description: string;
  testCases: { input: string; expectedOutput: string }[];
  judgeLimits?: PublicJudgeLimits | null;
  judgePolicyLegacy?: boolean;
}

const challenge: PanelChallenge = {
  id: 'p-1',
  title: '언어별 제한 문제',
  difficulty: 'iron5',
  description: '설명',
  testCases: [],
  judgeLimits: policy,
};

const contest: Contest = {
  id: 'contest-1', title: '신입생 대회', description: '', startsAt: '2099-01-01T00:00:00Z', endsAt: '2099-01-01T03:00:00Z', serverTime: '2099-01-01T01:00:00Z',
  state: 'running', published: true, joined: true, canManage: false, participantCount: 1, problems: [],
};

function renderPanel(overrides: Partial<PanelChallenge> = {}, contestContext?: Contest) {
  return render(
    <MemoryRouter>
      <ChallengePanel challenge={{ ...challenge, ...overrides }} code="print(1)" contest={contestContext} />
    </MemoryRouter>,
  );
}

describe('ChallengePanel judge limits', () => {
  beforeEach(() => {
    useCompilerStore.setState(initialStore, true);
    useCompilerStore.setState({ language: 'bpp' });
  });

  afterEach(() => {
    cleanup();
    useCompilerStore.setState(initialStore, true);
  });

  it.each([
    ['python', 'Python 실행 기준', '2.75초', 'CPython 3.13'],
    ['java', 'Java 실행 기준', '3.5초', 'OpenJDK 21'],
  ] as const)('uses the selected %s limits instead of a B++ fallback', (language, heading, cpu, runtime) => {
    renderPanel();

    act(() => useCompilerStore.getState().setLanguage(language));

    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.getAllByText(cpu)).not.toHaveLength(0);
    expect(screen.getAllByText(runtime)).not.toHaveLength(0);
  });

  it('shows the saved legacy warning without manufacturing current shared limits', () => {
    renderPanel({ judgeLimits: null, judgePolicyLegacy: true });

    expect(screen.getByText('기존 문제 정책')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('현재 공통 제한을 추정해 표시하지 않습니다.');
    expect(screen.queryByRole('heading', { name: 'B++ 실행 기준' })).not.toBeInTheDocument();
    expect(screen.queryByText('1.25초')).not.toBeInTheDocument();
  });

  it('does not invent limits for a new problem whose policy is still unmeasured', () => {
    renderPanel({ judgeLimits: null, judgePolicyLegacy: false });

    expect(screen.getByRole('status')).toHaveTextContent('확정된 언어별 제한이 아직 없습니다.');
    expect(screen.queryByRole('heading', { name: 'B++ 실행 기준' })).not.toBeInTheDocument();
    expect(screen.queryByText('1.25초')).not.toBeInTheDocument();
  });

  it('keeps the policy visible in contest problem context alongside contest submission', () => {
    renderPanel({}, contest);

    expect(screen.getByRole('heading', { name: '채점 제한' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '대회 제출' })).toBeInTheDocument();
  });
});
