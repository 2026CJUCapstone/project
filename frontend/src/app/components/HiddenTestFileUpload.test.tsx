import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setAuthToken } from '../services/authIdentity';
import { HiddenTestUploadError } from '../services/judgeTestDataApi';
import { HiddenTestFileUpload } from './HiddenTestFileUpload';
import type { StoredHiddenTestCase } from '../services/problemApi';

const mocks = vi.hoisted(() => ({ uploadHiddenTestFiles: vi.fn() }));

vi.mock('../services/judgeTestDataApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/judgeTestDataApi')>(),
  uploadHiddenTestFiles: mocks.uploadHiddenTestFiles,
}));

const digest = (character: string) => `sha256:${character.repeat(64)}` as `sha256:${string}`;
const storedCase: StoredHiddenTestCase = {
  kind: 'stored-v1',
  inputRef: { digest: digest('a'), byteCount: 6, encoding: 'utf-8' },
  expectedOutputRef: { digest: digest('b'), byteCount: 7, encoding: 'utf-8' },
};

function signedInToken(sub = 'admin'): string {
  return `header.${btoa(JSON.stringify({ sub }))}.signature`;
}

async function selectBothFiles() {
  const user = userEvent.setup();
  await user.upload(screen.getByLabelText('숨김 테스트 입력 파일'), new File(['input\n'], 'input.txt', { type: 'text/plain' }));
  await user.upload(screen.getByLabelText('숨김 테스트 정답 파일'), new File(['output\n'], 'output.txt', { type: 'text/plain' }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}

describe('HiddenTestFileUpload', () => {
  afterEach(() => {
    setAuthToken(null);
    mocks.uploadHiddenTestFiles.mockReset();
  });

  it('does not start a network upload until both files are selected and the explicit button is clicked', async () => {
    setAuthToken(signedInToken());
    const onUploaded = vi.fn();
    mocks.uploadHiddenTestFiles.mockResolvedValue(storedCase);
    render(<HiddenTestFileUpload targetKey="new-problem" onUploaded={onUploaded} />);

    await selectBothFiles();
    expect(mocks.uploadHiddenTestFiles).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '숨김 테스트 업로드' }));

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(storedCase));
    expect(mocks.uploadHiddenTestFiles).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('파일 내용은 화면에 표시하지 않습니다');
    expect(screen.getByLabelText('숨김 테스트 입력 파일')).toHaveValue('');
    expect(screen.getByLabelText('숨김 테스트 정답 파일')).toHaveValue('');
  });

  it('does not change the parent list when only one server blob succeeded', async () => {
    setAuthToken(signedInToken());
    const onUploaded = vi.fn();
    mocks.uploadHiddenTestFiles.mockRejectedValue(new HiddenTestUploadError('정답 파일 업로드에 실패했습니다.', true));
    render(<HiddenTestFileUpload targetKey="new-problem" onUploaded={onUploaded} />);

    await selectBothFiles();
    fireEvent.click(screen.getByRole('button', { name: '숨김 테스트 업로드' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('숨김 테스트 목록은 변경하지 않았습니다');
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it('does not append a late upload after the form target changes', async () => {
    setAuthToken(signedInToken('alice'));
    const onUploaded = vi.fn();
    const lateUpload = deferred<StoredHiddenTestCase>();
    mocks.uploadHiddenTestFiles.mockReturnValue(lateUpload.promise);
    const { rerender } = render(<HiddenTestFileUpload targetKey="old-form" onUploaded={onUploaded} />);

    await selectBothFiles();
    fireEvent.click(screen.getByRole('button', { name: '숨김 테스트 업로드' }));
    await waitFor(() => expect(mocks.uploadHiddenTestFiles).toHaveBeenCalledTimes(1));
    rerender(<HiddenTestFileUpload targetKey="new-form" onUploaded={onUploaded} />);

    await act(async () => { lateUpload.resolve(storedCase); });
    expect(onUploaded).not.toHaveBeenCalled();
  });
});
