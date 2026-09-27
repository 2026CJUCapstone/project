import { describe, expect, it, vi } from 'vitest';
import {
  MAX_JUDGE_TEST_DATA_BYTES,
  prepareJudgeTestData,
  uploadHiddenTestFiles,
  uploadJudgeTestData,
} from './judgeTestDataApi';

const digest = `sha256:${'a'.repeat(64)}` as `sha256:${string}`;

function fileFromBytes(bytes: Uint8Array): File {
  return {
    size: bytes.byteLength,
    arrayBuffer: vi.fn().mockResolvedValue(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)),
  } as unknown as File;
}

function receipt(byteCount: number, extra: Record<string, unknown> = {}): Response {
  return new Response(JSON.stringify({ digest, byteCount, encoding: 'utf-8', replayed: false, ...extra }), {
    headers: { 'Content-Type': 'application/json' },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(nextResolve => { resolve = nextResolve; });
  return { promise, resolve };
}

describe('judgeTestDataApi', () => {
  it('hashes both UTF-8 files and adds a stored case only after exact receipts for both uploads', async () => {
    const input = new TextEncoder().encode('input\n');
    const expectedOutput = new TextEncoder().encode('output\n');
    const digestMock = vi.fn().mockResolvedValue(new Uint8Array(32).fill(0xaa).buffer);
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(receipt(input.byteLength))
      .mockResolvedValueOnce(receipt(expectedOutput.byteLength));
    vi.stubGlobal('crypto', { subtle: { digest: digestMock } });
    vi.stubGlobal('fetch', fetchMock);

    const testCase = await uploadHiddenTestFiles(fileFromBytes(input), fileFromBytes(expectedOutput));

    expect(testCase).toEqual({
      kind: 'stored-v1',
      inputRef: { digest, byteCount: input.byteLength, encoding: 'utf-8' },
      expectedOutputRef: { digest, byteCount: expectedOutput.byteLength, encoding: 'utf-8' },
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/admin/judge-test-data/${'a'.repeat(64)}?byteCount=${input.byteLength}`);
    expect(fetchMock.mock.calls[1][0]).toBe(`/api/v1/admin/judge-test-data/${'a'.repeat(64)}?byteCount=${expectedOutput.byteLength}`);
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(request).toMatchObject({ method: 'PUT', headers: expect.objectContaining({ 'Content-Type': 'application/octet-stream' }) });
    expect(Array.from(new Uint8Array(request.body as ArrayBuffer))).toEqual(Array.from(input));
    expect(digestMock).toHaveBeenCalledTimes(2);
  });

  it('rejects an invalid UTF-8 file and a 16 MiB + 1 file before any upload', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const invalidUtf8 = fileFromBytes(new Uint8Array([0xff]));
    const tooLargeRead = vi.fn();
    const tooLarge = { size: MAX_JUDGE_TEST_DATA_BYTES + 1, arrayBuffer: tooLargeRead } as unknown as File;

    await expect(prepareJudgeTestData(invalidUtf8)).rejects.toThrow('유효한 UTF-8');
    await expect(prepareJudgeTestData(tooLarge)).rejects.toThrow('이하만 업로드');
    expect(tooLargeRead).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects a server receipt that does not exactly identify the local bytes', async () => {
    const prepared = { bytes: new Uint8Array([1, 2, 3]), digest };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(receipt(999)));

    await expect(uploadJudgeTestData(prepared)).rejects.toThrow('일치하지 않습니다');
  });

  it('rejects a receipt with extra fields even if its identity otherwise matches', async () => {
    const prepared = { bytes: new Uint8Array([1, 2, 3]), digest };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(receipt(3, { unexpected: 'ignored values are forbidden' })));

    await expect(uploadJudgeTestData(prepared)).rejects.toThrow('응답 형식이 올바르지 않습니다');
  });

  it('abandons a file preparation that becomes stale while reading', async () => {
    const read = deferred<ArrayBuffer>();
    const file = { size: 2, arrayBuffer: vi.fn().mockReturnValue(read.promise) } as unknown as File;
    let current = true;
    const task = prepareJudgeTestData(file, undefined, () => current);
    current = false;
    read.resolve(new Uint8Array([0x61, 0x0a]).buffer);

    await expect(task).rejects.toMatchObject({ name: 'AbortError' });
  });
});
