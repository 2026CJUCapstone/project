import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReferenceSolutionValidationPanel } from './ReferenceSolutionValidationPanel';
import type { JudgePolicy } from '../services/judgePolicyTypes';
import type { ProblemAuthoringRecord } from '../services/problemAuthoringApi';
import type { AuthoringValidationReceipt } from '../services/authoringValidationApi';
import { ApiError } from '../services/apiBase';

const mocks = vi.hoisted(() => ({ create: vi.fn(), wait: vi.fn(), createProblem: vi.fn(), waitProblem: vi.fn(), createRejudge: vi.fn(), waitRejudge: vi.fn() }));

vi.mock('../services/authoringValidationApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/authoringValidationApi')>(),
  createAuthoringValidation: mocks.create,
  waitForAuthoringValidation: mocks.wait,
  createProblemAuthoringValidation: mocks.createProblem,
  waitForProblemAuthoringValidation: mocks.waitProblem,
  createRejudgeAuthoringValidation: mocks.createRejudge,
  waitForRejudgeAuthoringValidation: mocks.waitRejudge,
}));

const digest = (character: string) => `sha256:${character.repeat(64)}`;
const referenceDigest = digest('a');

function policy(reviewStatus: JudgePolicy['reviewStatus'] = 'verified'): JudgePolicy {
  const limits = { cpuMs: 1_000, wallMs: 2_000, memoryBytes: 128 * 1024 ** 2, outputBytes: 1024, pids: 16, tmpBytes: 1024 };
  return {
    schemaVersion: 1,
    policyId: 'freshman-policy',
    revision: 3,
    reviewStatus,
    testSuiteHash: digest('b'),
    profiles: {
      python: {
        runtimeId: 'python-3', runtimeVersion: '3.13', imageDigest: digest('c'), workerClass: 'linux-amd64', toolchainProfile: 'python-default',
        compile: limits, run: limits,
      },
    },
    ...(reviewStatus === 'verified' ? { evidence: {
      python: {
        reportHash: digest('d'), resourceFingerprint: digest('e'), hostClass: 'linux-amd64', repetitions: 10, caseCount: 2,
        maxCpuMs: 10, maxWallMs: 20, peakMemoryBytes: 1024, safetyMarginReason: 'measured headroom',
      },
    } } : {}),
    preparationCleanupMs: 1_000,
  };
}

function authoring(fingerprint = digest('f')): ProblemAuthoringRecord {
  return {
    problemId: 'problem-1',
    fingerprint,
    metadata: {
      sources: [{ url: 'https://example.com/problem', title: 'source' }],
      adaptationNotes: 'adapted',
      requiredLanguages: ['python'],
      assets: [{ role: 'reference', name: 'solution.py', language: 'python', digest: referenceDigest }],
    },
    categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' },
    events: [],
  };
}

function receipt(status: AuthoringValidationReceipt['status'], result: AuthoringValidationReceipt['result'] = null): AuthoringValidationReceipt {
  return {
    id: 'validation-1', status, receivedAt: '2030-01-01T00:00:00Z', finishedAt: status === 'completed' ? '2030-01-01T00:00:01Z' : null,
    language: 'python', sourceHash: referenceDigest, authoringFingerprint: digest('f'), referenceAssetDigest: referenceDigest,
    problemSnapshotHash: digest('1'), policyHash: digest('2'), testSuiteHash: digest('3'), result,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(next => { resolve = next; });
  return { promise, resolve };
}

describe('ReferenceSolutionValidationPanel', () => {
  beforeEach(() => {
    mocks.create.mockReset().mockResolvedValue(receipt('queued'));
    mocks.wait.mockReset().mockResolvedValue(receipt('completed', {
      verdict: 'accepted',
      resourceUsage: {
        version: 1, measurement: 'cgroup-v2-whole-phase', policyId: 'freshman-policy', policyRevision: 3,
        compile: { cpuMs: 10, wallMs: 20, peakMemoryBytes: 4096 },
        run: { cpuMs: 30, wallMs: 40, peakMemoryBytes: 8192, maxCpuMs: 15, maxWallMs: 20 },
      },
    }));
    mocks.createProblem.mockReset().mockResolvedValue(receipt('queued'));
    mocks.waitProblem.mockReset().mockResolvedValue(receipt('completed', { verdict: 'accepted', resourceUsage: null }));
    mocks.createRejudge.mockReset().mockResolvedValue(receipt('queued'));
    mocks.waitRejudge.mockReset().mockResolvedValue(receipt('completed', { verdict: 'accepted', resourceUsage: null }));
  });

  afterEach(() => vi.clearAllMocks());

  it('submits the exact saved fingerprint and reference digest, then renders only the bounded result', async () => {
    render(<ReferenceSolutionValidationPanel contestId="contest / one" contestProblemId="row / one" policy={policy()} authoring={authoring()} isAdmin />);

    expect(await screen.findByRole('combobox', { name: '기준 풀이 검증 언어' })).toHaveValue('python');
    fireEvent.change(screen.getByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(42)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith('contest / one', 'row / one', expect.objectContaining({
      code: 'print(42)', language: 'python', expectedFingerprint: digest('f'), referenceAssetDigest: referenceDigest,
      requestId: expect.any(String),
    }), expect.any(AbortSignal));
    await screen.findByText('정답');
    expect(screen.getByText(/실행 CPU 최대/)).toBeInTheDocument();
    expect(screen.queryByText(/secret|hidden/i)).not.toBeInTheDocument();
  });

  it('targets the frozen rejudge candidate instead of the live contest problem', async () => {
    render(<ReferenceSolutionValidationPanel contestId="contest" rejudgeBatchId="batch" policy={policy()} authoring={authoring()} isAdmin />);
    fireEvent.change(await screen.findByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(43)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await waitFor(() => expect(mocks.createRejudge).toHaveBeenCalledOnce());
    expect(mocks.createRejudge).toHaveBeenCalledWith('contest', 'batch', expect.objectContaining({
      code: 'print(43)', expectedFingerprint: digest('f'), referenceAssetDigest: referenceDigest,
    }), expect.any(AbortSignal));
    expect(mocks.create).not.toHaveBeenCalled();
    await screen.findByText('정답');
  });

  it('runs the saved standalone problem through its generic authoring-validation scope', async () => {
    render(<ReferenceSolutionValidationPanel problemId="problem-1" policy={policy()} authoring={authoring()} isAdmin />);
    fireEvent.change(await screen.findByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(44)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));

    await waitFor(() => expect(mocks.createProblem).toHaveBeenCalledOnce());
    expect(mocks.createProblem).toHaveBeenCalledWith('problem-1', expect.objectContaining({
      code: 'print(44)', language: 'python', expectedFingerprint: digest('f'), referenceAssetDigest: referenceDigest,
      requestId: expect.any(String),
    }), expect.any(AbortSignal));
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.createRejudge).not.toHaveBeenCalled();
    await screen.findByText('정답');
  });

  it('does not offer execution without a verified policy or a saved contest problem row', () => {
    const { rerender } = render(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-1" policy={policy('draft')} authoring={authoring()} isAdmin />);
    expect(screen.getByRole('status')).toHaveTextContent('검증된 언어별 채점 제한');
    expect(screen.queryByRole('button', { name: '기준 풀이 실행' })).not.toBeInTheDocument();

    rerender(<ReferenceSolutionValidationPanel policy={policy()} authoring={authoring()} isAdmin />);
    expect(screen.getByRole('status')).toHaveTextContent('문제를 먼저 저장');
  });

  it('aborts and fences a pending private validation when its problem scope changes', async () => {
    const pending = deferred<AuthoringValidationReceipt>();
    mocks.create.mockReturnValueOnce(pending.promise);
    const { rerender } = render(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-1" policy={policy()} authoring={authoring()} isAdmin />);
    await screen.findByRole('combobox', { name: '기준 풀이 검증 언어' });
    fireEvent.change(screen.getByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(42)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const signal = mocks.create.mock.calls[0][3] as AbortSignal;

    rerender(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-2" policy={policy()} authoring={authoring(digest('9'))} isAdmin />);
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(receipt('completed', { verdict: 'accepted', resourceUsage: null })));
    expect(screen.queryByRole('region', { name: '기준 풀이 검증 결과' })).not.toBeInTheDocument();
  });

  it('keeps the active receipt when an equivalent saved snapshot is re-read as new objects', async () => {
    const pending = deferred<AuthoringValidationReceipt>();
    mocks.create.mockReturnValueOnce(pending.promise);
    const originalPolicy = policy();
    const originalAuthoring = authoring();
    const { rerender } = render(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-1" policy={originalPolicy} authoring={originalAuthoring} isAdmin />);
    await screen.findByRole('combobox', { name: '기준 풀이 검증 언어' });
    fireEvent.change(screen.getByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(42)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const signal = mocks.create.mock.calls[0][3] as AbortSignal;

    rerender(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-1" policy={structuredClone(originalPolicy)} authoring={structuredClone(originalAuthoring)} isAdmin />);
    expect(signal.aborted).toBe(false);
    expect(screen.getByRole('textbox', { name: '기준 풀이 코드' })).toHaveValue('print(42)');

    await act(async () => pending.resolve(receipt('queued')));
    await screen.findByText('정답');
  });

  it('reuses the request ID after a non-expired API error when retrying the same source', async () => {
    mocks.create.mockRejectedValueOnce(new ApiError('일시적인 오류입니다.', 503));
    render(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-1" policy={policy()} authoring={authoring()} isAdmin />);

    await screen.findByRole('combobox', { name: '기준 풀이 검증 언어' });
    fireEvent.change(screen.getByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(42)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await screen.findByText('일시적인 오류입니다.');
    const firstRequestId = (mocks.create.mock.calls[0][2] as { requestId: string }).requestId;

    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
    expect((mocks.create.mock.calls[1][2] as { requestId: string }).requestId).toBe(firstRequestId);
    await screen.findByText('정답');
  });

  it('starts a new validation after an expired receipt while retaining ambiguous retry keys', async () => {
    mocks.wait.mockRejectedValueOnce(new ApiError('검증 결과가 만료되었습니다.', 410));
    render(<ReferenceSolutionValidationPanel contestId="contest-1" contestProblemId="row-1" policy={policy()} authoring={authoring()} isAdmin />);

    await screen.findByRole('combobox', { name: '기준 풀이 검증 언어' });
    fireEvent.change(screen.getByRole('textbox', { name: '기준 풀이 코드' }), { target: { value: 'print(42)' } });
    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await screen.findByText('이전 검증 결과가 만료되었습니다. 다시 실행하여 새 검증을 시작하세요.');
    const firstRequestId = (mocks.create.mock.calls[0][2] as { requestId: string }).requestId;

    fireEvent.click(screen.getByRole('button', { name: '기준 풀이 실행' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
    expect((mocks.create.mock.calls[1][2] as { requestId: string }).requestId).not.toBe(firstRequestId);
    await screen.findByText('정답');
  });
});
