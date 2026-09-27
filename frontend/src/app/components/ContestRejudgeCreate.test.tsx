import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../services/authIdentity';
import type { ContestRejudgeContext, ContestRejudgeCreateRequest } from '../services/contestRejudgeApi';
import type { JudgePolicy } from '../services/judgePolicyTypes';
import type { HiddenTestCase, Sha256Digest } from '../services/problemApi';
import type { AuthoringMetadata } from '../services/problemAuthoringApi';
import { ContestRejudgeCreate } from './ContestRejudgeCreate';

const mocks = vi.hoisted(() => ({
  getContext: vi.fn(),
  create: vi.fn(),
  replacement: null as unknown,
  uploaded: null as unknown,
}));

vi.mock('../services/contestRejudgeApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestRejudgeApi')>(),
  getContestRejudgeContext: mocks.getContext,
  createContestRejudge: mocks.create,
}));

type PolicyEditorProps = { policy?: JudgePolicy | null; onReplace: (policy: JudgePolicy) => void };
vi.mock('./JudgePolicyEditor', () => ({
  JudgePolicyEditor: ({ policy, onReplace }: PolicyEditorProps) => <section aria-label="mock policy editor">
    <output data-testid="policy-revision">{policy?.revision ?? 'none'}</output>
    <button type="button" onClick={() => onReplace(mocks.replacement as JudgePolicy)}>검증 정책 가져오기</button>
  </section>,
}));

type HiddenUploadProps = { disabled?: boolean; onUploaded: (testCase: HiddenTestCase) => void };
vi.mock('./HiddenTestFileUpload', () => ({
  HiddenTestFileUpload: ({ disabled, onUploaded }: HiddenUploadProps) => <button type="button" disabled={disabled} onClick={() => onUploaded(mocks.uploaded as HiddenTestCase)}>저장 참조 추가</button>,
}));

function digest(character = 'a'): Sha256Digest {
  return `sha256:${character.repeat(64)}` as Sha256Digest;
}

function signedInToken(sub = 'admin'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

function policy(revision: number): JudgePolicy {
  const limits = { cpuMs: 100, wallMs: 200, memoryBytes: 128 * 1024 * 1024, outputBytes: 1024, pids: 8, tmpBytes: 1024 };
  return {
    schemaVersion: 1,
    policyId: 'measured-policy',
    revision,
    reviewStatus: 'verified',
    testSuiteHash: digest('b'),
    profiles: {
      python: {
        runtimeId: 'python-3', runtimeVersion: '3.12', imageDigest: digest('c'), workerClass: 'measured-linux', toolchainProfile: 'python-default',
        compile: limits, run: limits,
      },
    },
    evidence: {
      python: {
        reportHash: digest('d'), resourceFingerprint: digest('e'), hostClass: 'measured-linux', repetitions: 10, caseCount: 1,
        maxCpuMs: 1, maxWallMs: 1, peakMemoryBytes: 1, safetyMarginReason: 'Measured in the selected worker class.',
      },
    },
    preparationCleanupMs: 1_000,
  };
}

const authoring: AuthoringMetadata = {
  sources: [{ url: 'https://example.test/problem', title: '원본 문제', reuseBasis: 'original', reuseEvidence: '작성자가 원본임을 확인했습니다.' }],
  adaptationNotes: '재채점 후보의 출처 메타데이터입니다.',
  assets: [{ role: 'reference', name: 'reference.py', digest: digest('7'), language: 'python' }],
  requiredLanguages: ['python'],
};

function context(): ContestRejudgeContext {
  return {
    contestProblemId: 'cp-1',
    snapshotHash: digest('f'),
    snapshot: {
      sample: [{ input: '1\n', expectedOutput: '1\n' }],
      hidden: [{ kind: 'stored-v1', inputRef: { digest: digest('1'), byteCount: 2, encoding: 'utf-8' }, expectedOutputRef: { digest: digest('2'), byteCount: 2, encoding: 'utf-8' } }],
      judgePolicy: policy(1),
      authoring,
      preservedServerMetadata: { title: 'A' },
    },
  };
}

function renderPanel() {
  const onCreated = vi.fn();
  const onAccessLost = vi.fn();
  render(<ContestRejudgeCreate contestId="contest-1" problems={[{ id: 'cp-1', label: 'A', title: '테스트 문제' }]} onCreated={onCreated} onAccessLost={onAccessLost} />);
  return { onCreated, onAccessLost };
}

async function loadContext() {
  const callbacks = renderPanel();
  fireEvent.change(screen.getByLabelText('재채점 문제'), { target: { value: 'cp-1' } });
  fireEvent.click(screen.getByRole('button', { name: '현재 테스트 불러오기' }));
  await waitFor(() => expect(mocks.getContext).toHaveBeenCalledWith('contest-1', 'cp-1', expect.any(AbortSignal)));
  return callbacks;
}

async function prepareSubmission() {
  const callbacks = await loadContext();
  fireEvent.click(screen.getByRole('button', { name: '검증 정책 가져오기' }));
  fireEvent.change(screen.getByLabelText('관리자 변경 사유'), { target: { value: 'Correct the final results after measured verification.' } });
  fireEvent.click(screen.getByRole('checkbox', { name: '원래 점수는 유지하고 후보 채점만 시작합니다.' }));
  return callbacks;
}

describe('ContestRejudgeCreate', () => {
  beforeEach(() => {
    setAuthToken(signedInToken());
    mocks.getContext.mockReset();
    mocks.create.mockReset();
    mocks.getContext.mockResolvedValue(context());
    mocks.create.mockResolvedValue({ id: 'batch-1' });
    mocks.replacement = policy(2);
    mocks.uploaded = { kind: 'stored-v1', inputRef: { digest: digest('3'), byteCount: 3, encoding: 'utf-8' }, expectedOutputRef: { digest: digest('4'), byteCount: 3, encoding: 'utf-8' } } satisfies HiddenTestCase;
    vi.stubGlobal('crypto', { randomUUID: vi.fn(() => 'request-id') });
  });

  afterEach(() => {
    setAuthToken(null);
    vi.unstubAllGlobals();
  });

  it('loads a selected context only on an explicit action and never creates a candidate automatically', async () => {
    renderPanel();

    expect(mocks.getContext).not.toHaveBeenCalled();
    expect(mocks.create).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('재채점 문제'), { target: { value: 'cp-1' } });
    expect(mocks.getContext).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '현재 테스트 불러오기' }));

    await waitFor(() => expect(mocks.getContext).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('수정한 예제 JSON')).toHaveValue(JSON.stringify(context().snapshot.sample, null, 2));
    expect(screen.getByLabelText('정정 출처 메타데이터 JSON')).toHaveValue(JSON.stringify(authoring, null, 2));
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it('uses a verified replacement supplied by the policy editor when creating the staged candidate', async () => {
    const { onCreated } = await prepareSubmission();

    expect(screen.getByTestId('policy-revision')).toHaveTextContent('2');
    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    const [, payload, signal] = mocks.create.mock.calls[0] as [string, ContestRejudgeCreateRequest, AbortSignal];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(payload).toEqual({
      requestId: 'request-id',
      contestProblemId: 'cp-1',
      expectedSnapshotHash: digest('f'),
      reason: 'Correct the final results after measured verification.',
      sample: context().snapshot.sample,
      hidden: context().snapshot.hidden,
      judgePolicy: policy(2),
    });
    expect(onCreated).toHaveBeenCalledOnce();
  });

  it('keeps the same request ID for an explicit retry after an ambiguous network failure', async () => {
    mocks.create.mockRejectedValueOnce(new Error('network interrupted')).mockResolvedValueOnce({ id: 'batch-1' });
    await prepareSubmission();

    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));
    await screen.findByRole('alert');
    expect(mocks.create).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
    const first = (mocks.create.mock.calls[0][1] as ContestRejudgeCreateRequest).requestId;
    const second = (mocks.create.mock.calls[1][1] as ContestRejudgeCreateRequest).requestId;
    expect(second).toBe(first);
  });

  it('generates a new request ID when an edited payload is submitted after an ambiguous failure', async () => {
    vi.stubGlobal('crypto', { randomUUID: vi.fn().mockReturnValueOnce('request-one').mockReturnValueOnce('request-two') });
    mocks.create.mockRejectedValueOnce(new Error('network interrupted')).mockResolvedValueOnce({ id: 'batch-1' });
    await prepareSubmission();

    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));
    await screen.findByRole('alert');
    fireEvent.change(screen.getByLabelText('수정한 예제 JSON'), { target: { value: '[{"input":"2\\n","expectedOutput":"2\\n"}]' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '원래 점수는 유지하고 후보 채점만 시작합니다.' }));
    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
    const first = mocks.create.mock.calls[0][1] as ContestRejudgeCreateRequest;
    const second = mocks.create.mock.calls[1][1] as ContestRejudgeCreateRequest;
    expect(second.requestId).not.toBe(first.requestId);
    expect(second.sample).toEqual([{ input: '2\n', expectedOutput: '2\n' }]);
  });

  it('clears staged confirmation when samples, hidden tests, policy, or the reason changes', async () => {
    await loadContext();
    const confirmation = screen.getByRole('checkbox', { name: '원래 점수는 유지하고 후보 채점만 시작합니다.' });
    const confirm = () => fireEvent.click(confirmation);
    const expectCleared = () => expect(confirmation).not.toBeChecked();

    fireEvent.change(screen.getByLabelText('관리자 변경 사유'), { target: { value: 'Correct the final results after measured verification.' } });
    confirm();
    fireEvent.change(screen.getByLabelText('수정한 예제 JSON'), { target: { value: '[{"input":"2\\n","expectedOutput":"2\\n"}]' } });
    expectCleared();

    confirm();
    fireEvent.click(screen.getByRole('button', { name: '저장 참조 추가' }));
    expectCleared();

    confirm();
    mocks.replacement = policy(2);
    fireEvent.click(screen.getByRole('button', { name: '검증 정책 가져오기' }));
    expectCleared();

    confirm();
    fireEvent.change(screen.getByLabelText('관리자 변경 사유'), { target: { value: 'A different public correction reason for participants.' } });
    expectCleared();
  });

  it('omits untouched metadata but submits explicitly edited provenance with the candidate', async () => {
    const { onCreated } = await prepareSubmission();
    fireEvent.change(screen.getByLabelText('정정 출처 메타데이터 JSON'), { target: { value: JSON.stringify({ ...authoring, adaptationNotes: '수정한 테스트와 측정 근거를 검토했습니다.' }) } });
    fireEvent.click(screen.getByRole('checkbox', { name: '원래 점수는 유지하고 후보 채점만 시작합니다.' }));
    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce());
    expect((mocks.create.mock.calls[0][1] as ContestRejudgeCreateRequest).authoring).toEqual({ ...authoring, adaptationNotes: '수정한 테스트와 측정 근거를 검토했습니다.' });
    expect(onCreated).toHaveBeenCalledOnce();
  });

  it('does not permit an edited metadata field to clear the frozen provenance with an empty value', async () => {
    await prepareSubmission();
    fireEvent.change(screen.getByLabelText('정정 출처 메타데이터 JSON'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '원래 점수는 유지하고 후보 채점만 시작합니다.' }));
    fireEvent.click(screen.getByRole('button', { name: '후보 채점 시작' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('비워서 지울 수 없습니다');
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
