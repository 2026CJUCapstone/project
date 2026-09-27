import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../services/authIdentity';
import { ProblemAuthoringPanel } from './ProblemAuthoringPanel';
import type { ProblemAuthoringRecord } from '../services/problemAuthoringApi';

const fingerprint = `sha256:${'a'.repeat(64)}`;
const digest = `sha256:${'b'.repeat(64)}`;

function signedInToken(sub = 'authoring-admin'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}

function record(problemId = 'problem-1', sourceTitle = '기존 출처'): ProblemAuthoringRecord {
  return {
    problemId,
    fingerprint,
    metadata: {
      sources: [{ url: 'https://example.test/problem', title: sourceTitle, reuseBasis: 'permission', reuseEvidence: 'author email' }],
      adaptationNotes: '입출력 형식과 설명을 독자적으로 정리했습니다.',
      assets: [{ role: 'reference', name: 'solution.py', digest, language: 'python' }],
      requiredLanguages: ['python'],
    },
    categories: { sources: 'pending', statement: 'pending', tests: 'pending', resources: 'pending' },
    events: [],
  };
}

describe('ProblemAuthoringPanel', () => {
  afterEach(() => {
    setAuthToken(null);
    vi.unstubAllGlobals();
  });

  it('keeps the protected API idle outside the existing admin boundary', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    render(<ProblemAuthoringPanel problemId="problem-1" isAdmin={false} />);
    expect(screen.getByText(/관리자 계정에서만/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('keeps exact raw metadata in the editor after a server conflict', async () => {
    setAuthToken(signedInToken());
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(record()))
      .mockResolvedValueOnce(response({ detail: '문제가 변경되었습니다.' }, 409));
    vi.stubGlobal('fetch', fetchMock);
    render(<ProblemAuthoringPanel problemId="problem-1" isAdmin />);

    const editor = await screen.findByRole('textbox', { name: '출처 메타데이터 JSON' });
    const draft = JSON.stringify({
      sources: [{ url: 'https://example.test/updated', title: '계속 작성 중인 출처', reuseBasis: 'original', reuseEvidence: 'team notes' }],
      adaptationNotes: '현재 초안을 서버 충돌에도 잃지 않습니다.',
      requiredLanguages: ['bpp', 'python'],
    });
    fireEvent.change(editor, { target: { value: draft } });
    fireEvent.click(screen.getByRole('button', { name: '출처 메타데이터 저장' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('작성 중인 내용은 보존했습니다');
    expect(editor).toHaveValue(draft);
    expect(screen.getByRole('button', { name: '최신 내용 확인' })).toBeInTheDocument();
  });

  it('requires a note and explicit approval click before making a mocked review request', async () => {
    setAuthToken(signedInToken());
    const approved = { ...record(), categories: { sources: 'approved', statement: 'pending', tests: 'pending', resources: 'pending' } } satisfies ProblemAuthoringRecord;
    const fetchMock = vi.fn().mockResolvedValueOnce(response(record())).mockResolvedValueOnce(response(approved));
    vi.stubGlobal('fetch', fetchMock);
    render(<ProblemAuthoringPanel problemId="problem-1" isAdmin />);

    await screen.findByText('기존 출처');
    const approval = screen.getByRole('button', { name: '승인 기록' });
    expect(approval).toBeDisabled();
    fireEvent.change(screen.getByRole('textbox', { name: '검수 메모' }), { target: { value: '이용 허가 근거와 원본 링크를 확인했습니다.' } });
    expect(approval).toBeEnabled();
    fireEvent.click(approval);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, request] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(String(request.body))).toMatchObject({
      expectedFingerprint: fingerprint,
      category: 'sources',
      decision: 'approved',
      note: '이용 허가 근거와 원본 링크를 확인했습니다.',
    });
    expect(JSON.parse(String(request.body)).requestId).toMatch(/^[a-zA-Z0-9._-]{1,80}$/);
    expect(await screen.findByRole('status')).toHaveTextContent('승인 기록을 저장했습니다');
  });

  it('requires saving a semantic metadata edit before approval can target server content', async () => {
    setAuthToken(signedInToken());
    const fetchMock = vi.fn().mockResolvedValueOnce(response(record()));
    vi.stubGlobal('fetch', fetchMock);
    render(<ProblemAuthoringPanel problemId="problem-1" isAdmin />);

    const editor = await screen.findByRole('textbox', { name: '출처 메타데이터 JSON' });
    fireEvent.change(editor, { target: { value: JSON.stringify({
      ...record().metadata,
      adaptationNotes: '서버에 저장하기 전 변경한 새 적응 기록입니다.',
    }) } });
    fireEvent.change(screen.getByRole('textbox', { name: '검수 메모' }), { target: { value: '저장된 버전을 확인할 예정입니다.' } });

    expect(screen.getByRole('status')).toHaveTextContent('먼저 출처 메타데이터를 저장한 뒤 승인할 수 있습니다');
    expect(screen.getByRole('button', { name: '승인 기록' })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('does not apply late private reads after problem or account scope changes', async () => {
    setAuthToken(signedInToken('alice'));
    const oldProblem = deferred<Response>();
    const oldAccount = deferred<Response>();
    const fetchMock = vi.fn()
      .mockReturnValueOnce(oldProblem.promise)
      .mockReturnValueOnce(oldAccount.promise)
      .mockResolvedValueOnce(response(record('problem-2', 'Bob의 최신 출처')));
    vi.stubGlobal('fetch', fetchMock);
    const { rerender } = render(<ProblemAuthoringPanel problemId="problem-1" isAdmin />);
    rerender(<ProblemAuthoringPanel problemId="problem-2" isAdmin />);
    act(() => setAuthToken(signedInToken('bob')));

    expect(await screen.findByText('Bob의 최신 출처')).toBeInTheDocument();
    await act(async () => {
      oldProblem.resolve(response(record('problem-1', 'Alice의 이전 출처')));
      oldAccount.resolve(response(record('problem-2', 'Alice의 다른 출처')));
    });
    expect(screen.getByText('Bob의 최신 출처')).toBeInTheDocument();
    expect(screen.queryByText('Alice의 이전 출처')).not.toBeInTheDocument();
    expect(screen.queryByText('Alice의 다른 출처')).not.toBeInTheDocument();
  });
});
