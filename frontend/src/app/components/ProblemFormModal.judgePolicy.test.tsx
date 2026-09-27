import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ProblemFormModal } from './ProblemFormModal';
import type { ProblemCreateRequest, StoredHiddenTestCase } from '../services/problemApi';
import type { JudgePolicy } from '../services/judgePolicyTypes';

const digest = (character: string) => `sha256:${character.repeat(64)}`;
const judgePolicy: JudgePolicy = {
  schemaVersion: 1, policyId: 'policy-1', revision: 1, reviewStatus: 'verified', testSuiteHash: digest('a'), preparationCleanupMs: 5000,
  profiles: {
    bpp: {
      runtimeId: 'bpp-runtime', runtimeVersion: 'B++ 1.0', imageDigest: digest('b'), workerClass: 'linux-amd64', toolchainProfile: 'standard',
      compile: { cpuMs: 2000, wallMs: 2500, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
      run: { cpuMs: 1000, wallMs: 1500, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
    },
  },
  evidence: {
    bpp: { reportHash: digest('c'), resourceFingerprint: digest('d'), hostClass: 'linux-amd64', repetitions: 20, caseCount: 10, maxCpuMs: 500, maxWallMs: 600, peakMemoryBytes: 64 * 1024 ** 2, safetyMarginReason: 'measured headroom' },
  },
};

const baseRequest: ProblemCreateRequest = {
  title: '문제', difficulty: 'iron5', tags: [], points: 100, description: '설명',
  testCases: [{ input: '1', expectedOutput: '1' }], hiddenTestCases: [],
};

const storedHiddenTest: StoredHiddenTestCase = {
  kind: 'stored-v1',
  inputRef: { digest: digest('d') as `sha256:${string}`, byteCount: 14_208, encoding: 'utf-8' },
  expectedOutputRef: { digest: digest('e') as `sha256:${string}`, byteCount: 3_072, encoding: 'utf-8' },
};

describe('ProblemFormModal judge policy wiring', () => {
  it('preserves an existing measured raw policy when editing and submitting', () => {
    const submit = vi.fn();
    render(<ProblemFormModal onClose={() => {}} onSubmit={submit} initialData={{ ...baseRequest, judgePolicy }} />);

    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ judgePolicy }));
  });

  it('omits a legacy null policy instead of treating it as a clear request', () => {
    const submit = vi.fn();
    render(<ProblemFormModal onClose={() => {}} onSubmit={submit} initialData={{ ...baseRequest, judgePolicy: null }} />);

    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit.mock.calls[0][0]).not.toHaveProperty('judgePolicy');
  });

  it('keeps a stored hidden-test reference exact when unrelated problem fields change', () => {
    const submit = vi.fn();
    render(<ProblemFormModal onClose={() => {}} onSubmit={submit} initialData={{ ...baseRequest, hiddenTestCases: [storedHiddenTest] }} />);

    expect(screen.getByText('채점 1 · 저장 참조')).toBeInTheDocument();
    expect(screen.getByText(/14,208 bytes/)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('채점 입력 1')).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText('문제 제목'), { target: { value: '바뀐 제목' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      title: '바뀐 제목',
      hiddenTestCases: [storedHiddenTest],
    }));
  });

  it('removes a stored reference only after the explicit delete action', () => {
    const submit = vi.fn();
    render(<ProblemFormModal onClose={() => {}} onSubmit={submit} initialData={{ ...baseRequest, hiddenTestCases: [storedHiddenTest] }} />);

    fireEvent.click(screen.getByRole('button', { name: '채점 1 삭제' }));
    fireEvent.click(screen.getByRole('button', { name: '저장' }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ hiddenTestCases: [] }));
  });

  it('continues to save edited inline hidden tests as inline content', () => {
    const submit = vi.fn();
    render(<ProblemFormModal onClose={() => {}} onSubmit={submit} initialData={baseRequest} />);

    fireEvent.change(screen.getByPlaceholderText('채점 입력 1'), { target: { value: '2\n' } });
    fireEvent.change(screen.getByPlaceholderText('채점 기대 출력 1'), { target: { value: '4\n' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ hiddenTestCases: [{ input: '2\n', expectedOutput: '4\n' }] }));
  });
});
