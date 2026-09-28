import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';
import type { Sha256Digest, StoredHiddenTestCase, StoredTestContentReference } from './problemApi';

export const MAX_JUDGE_TEST_DATA_BYTES = 16 * 1024 * 1024;
const MAX_RECEIPT_CHARS = 8 * 1024;

export interface PreparedJudgeTestData {
  readonly bytes: Uint8Array;
  readonly digest: Sha256Digest;
}

interface JudgeTestDataReceipt extends StoredTestContentReference {
  replayed: boolean;
}

export class HiddenTestUploadError extends Error {
  constructor(message: string, readonly partial: boolean) {
    super(message);
    this.name = 'HiddenTestUploadError';
  }
}

function abortError(): DOMException {
  return new DOMException('업로드가 취소되었습니다.', 'AbortError');
}

function assertCurrent(signal?: AbortSignal, isCurrent?: () => boolean): void {
  if (signal?.aborted || (isCurrent && !isCurrent())) throw abortError();
}

function hex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), byte => byte.toString(16).padStart(2, '0')).join('');
}

function contentReference(receipt: unknown, prepared: PreparedJudgeTestData): StoredTestContentReference {
  if (!receipt || typeof receipt !== 'object') throw new Error('테스트 데이터 업로드 응답 형식이 올바르지 않습니다.');
  const keys = Object.keys(receipt);
  const receiptKeys = ['digest', 'byteCount', 'encoding', 'replayed'];
  if (keys.length !== receiptKeys.length || keys.some(key => !receiptKeys.includes(key))) {
    throw new Error('테스트 데이터 업로드 응답 형식이 올바르지 않습니다.');
  }
  const value = receipt as Partial<JudgeTestDataReceipt>;
  if (value.digest !== prepared.digest || value.byteCount !== prepared.bytes.byteLength || value.encoding !== 'utf-8' || typeof value.replayed !== 'boolean') {
    throw new Error('서버의 테스트 데이터 영수증이 업로드한 파일의 해시·크기·인코딩과 일치하지 않습니다.');
  }
  return { digest: prepared.digest, byteCount: prepared.bytes.byteLength, encoding: 'utf-8' };
}

/** Reads, UTF-8-validates and hashes bytes locally. File contents are never rendered or logged. */
export async function prepareJudgeTestData(file: Pick<File, 'size' | 'arrayBuffer'>, signal?: AbortSignal, isCurrent?: () => boolean): Promise<PreparedJudgeTestData> {
  assertCurrent(signal, isCurrent);
  if (!Number.isInteger(file.size) || file.size < 0 || file.size > MAX_JUDGE_TEST_DATA_BYTES) {
    throw new Error(`테스트 파일은 0 bytes 이상 ${MAX_JUDGE_TEST_DATA_BYTES.toLocaleString('ko-KR')} bytes 이하만 업로드할 수 있습니다.`);
  }
  const arrayBuffer = await file.arrayBuffer();
  assertCurrent(signal, isCurrent);
  const bytes = new Uint8Array(arrayBuffer);
  if (bytes.byteLength !== file.size) throw new Error('선택한 파일 크기를 확인하지 못했습니다. 다시 선택해 주세요.');
  try {
    // Validation only: do not retain, render, or log decoded private content.
    new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    throw new Error('테스트 파일은 유효한 UTF-8 텍스트여야 합니다.');
  }
  assertCurrent(signal, isCurrent);
  if (!globalThis.crypto?.subtle) throw new Error('이 브라우저에서는 SHA-256 해시를 계산할 수 없습니다.');
  const exactBytes = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const hash = await globalThis.crypto.subtle.digest('SHA-256', exactBytes);
  assertCurrent(signal, isCurrent);
  return { bytes, digest: `sha256:${hex(hash)}` as Sha256Digest };
}

/** Uploads an already prepared immutable blob and rejects a mismatched receipt. */
export async function uploadJudgeTestData(prepared: PreparedJudgeTestData, signal?: AbortSignal, isCurrent?: () => boolean): Promise<StoredTestContentReference> {
  assertCurrent(signal, isCurrent);
  const sha256 = prepared.digest.slice('sha256:'.length);
  const response = await fetch(`${API_BASE_URL}/api/v1/admin/judge-test-data/${encodeURIComponent(sha256)}?byteCount=${prepared.bytes.byteLength}`, {
    method: 'PUT', signal,
    headers: { 'Content-Type': 'application/octet-stream', ...getAuthHeaders() },
    // Slice to an exact ArrayBuffer: DOM typings do not accept a possibly
    // shared backing buffer, and the server must receive only the original bytes.
    body: prepared.bytes.buffer.slice(prepared.bytes.byteOffset, prepared.bytes.byteOffset + prepared.bytes.byteLength) as ArrayBuffer,
  });
  assertCurrent(signal, isCurrent);
  if (!response.ok) throw await parseApiError(response, '테스트 데이터 업로드에 실패했습니다.');
  const declaredLength = response.headers.get('Content-Length');
  if (declaredLength !== null && (!/^\d+$/.test(declaredLength) || Number(declaredLength) > MAX_RECEIPT_CHARS)) {
    throw new Error('테스트 데이터 업로드 응답이 허용 크기를 초과했습니다.');
  }
  const receiptText = await response.text();
  assertCurrent(signal, isCurrent);
  if (receiptText.length > MAX_RECEIPT_CHARS) throw new Error('테스트 데이터 업로드 응답이 허용 크기를 초과했습니다.');
  let receipt: unknown;
  try {
    receipt = JSON.parse(receiptText);
  } catch {
    throw new Error('테스트 데이터 업로드 응답 JSON 형식이 올바르지 않습니다.');
  }
  return contentReference(receipt, prepared);
}

/**
 * Prepares both files before any write, then uploads them sequentially because
 * the server intentionally permits only one bounded upload at a time.
 */
export async function uploadHiddenTestFiles(inputFile: File, expectedOutputFile: File, signal?: AbortSignal, isCurrent?: () => boolean): Promise<StoredHiddenTestCase> {
  const input = await prepareJudgeTestData(inputFile, signal, isCurrent);
  const expectedOutput = await prepareJudgeTestData(expectedOutputFile, signal, isCurrent);
  assertCurrent(signal, isCurrent);
  let inputRef: StoredTestContentReference;
  try {
    inputRef = await uploadJudgeTestData(input, signal, isCurrent);
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new HiddenTestUploadError(error instanceof Error ? error.message : '입력 파일 업로드에 실패했습니다.', true);
  }
  try {
    const expectedOutputRef = await uploadJudgeTestData(expectedOutput, signal, isCurrent);
    assertCurrent(signal, isCurrent);
    return { kind: 'stored-v1', inputRef, expectedOutputRef };
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new HiddenTestUploadError(error instanceof Error ? error.message : '정답 파일 업로드에 실패했습니다.', true);
  }
}
