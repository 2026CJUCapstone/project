import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { FileUp, Loader2 } from 'lucide-react';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import { HiddenTestUploadError, MAX_JUDGE_TEST_DATA_BYTES, uploadHiddenTestFiles } from '../services/judgeTestDataApi';
import type { StoredHiddenTestCase } from '../services/problemApi';

function getAuthScope(): string {
  if (typeof window === 'undefined') return 'guest';
  const token = window.localStorage.getItem('authToken');
  return token && token !== 'undefined' && token !== 'null' ? `${getAuthOwner()}:${token}` : 'guest';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

export interface HiddenTestFileUploadProps {
  /** Changes whenever this UI is now editing a different problem/form target. */
  targetKey: string;
  disabled?: boolean;
  onUploaded: (testCase: StoredHiddenTestCase) => void;
  onBusyChange?: (busy: boolean) => void;
}

/** Explicit two-file upload for a private stored-v1 case; it never displays file contents. */
export function HiddenTestFileUpload({ targetKey, disabled = false, onUploaded, onBusyChange }: HiddenTestFileUploadProps) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  if (scope === 'guest') return null;
  return <HiddenTestFileUploadForScope key={`${scope}:${targetKey}`} targetKey={targetKey} scope={scope} disabled={disabled} onUploaded={onUploaded} onBusyChange={onBusyChange} />;
}

function HiddenTestFileUploadForScope({ targetKey, scope, disabled, onUploaded, onBusyChange }: HiddenTestFileUploadProps & { scope: string }) {
  const [inputFile, setInputFile] = useState<File | null>(null);
  const [expectedOutputFile, setExpectedOutputFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const mountedRef = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const inputFileRef = useRef<HTMLInputElement>(null);
  const expectedOutputFileRef = useRef<HTMLInputElement>(null);
  const onBusyChangeRef = useRef(onBusyChange);
  onBusyChangeRef.current = onBusyChange;

  const current = () => mountedRef.current && getAuthScope() === scope;
  const setBusy = (value: boolean) => {
    busyRef.current = value;
    if (current()) onBusyChangeRef.current?.(value);
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();
      if (busyRef.current) onBusyChangeRef.current?.(false);
    };
  }, [targetKey, scope]);

  const chooseInput = (file: File | null) => {
    setInputFile(file); setError(''); setNotice('');
  };
  const chooseExpectedOutput = (file: File | null) => {
    setExpectedOutputFile(file); setError(''); setNotice('');
  };

  const upload = async () => {
    if (uploading || disabled || !current()) return;
    if (!inputFile || !expectedOutputFile) {
      setError('입력 파일과 정답 파일을 모두 선택한 뒤 업로드해 주세요.');
      return;
    }
    const controller = new AbortController();
    controllerRef.current?.abort();
    controllerRef.current = controller;
    setUploading(true); setBusy(true); setError(''); setNotice('');
    try {
      const testCase = await uploadHiddenTestFiles(inputFile, expectedOutputFile, controller.signal, () => current() && controllerRef.current === controller);
      if (!current() || controllerRef.current !== controller) return;
      onUploaded(testCase);
      // File fields are uncontrolled by design. Clear their native values too,
      // so the visible selection cannot disagree with the reset React state.
      inputFileRef.current && (inputFileRef.current.value = '');
      expectedOutputFileRef.current && (expectedOutputFileRef.current.value = '');
      setInputFile(null); setExpectedOutputFile(null);
      setNotice('숨김 테스트 저장 참조를 추가했습니다. 파일 내용은 화면에 표시하지 않습니다.');
    } catch (uploadError) {
      if (!current() || controllerRef.current !== controller || isAbort(uploadError)) return;
      if (uploadError instanceof HiddenTestUploadError && uploadError.partial) {
        setError(`${uploadError.message} 숨김 테스트 목록은 변경하지 않았습니다. 서버의 멱등 저장 blob은 남아 있을 수 있습니다.`);
      } else {
        setError(uploadError instanceof Error ? uploadError.message : '숨김 테스트 파일 업로드에 실패했습니다.');
      }
    } finally {
      if (controllerRef.current === controller) {
        busyRef.current = false;
        if (current()) {
          setUploading(false);
          onBusyChangeRef.current?.(false);
        }
      }
    }
  };

  const fileLimit = `${(MAX_JUDGE_TEST_DATA_BYTES / 1024 / 1024).toLocaleString('ko-KR')} MiB`;
  return <section aria-label="숨김 테스트 파일 업로드" className="rounded border border-violet-300 bg-violet-50 p-3 text-sm text-violet-950 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-100">
    <h4 className="font-semibold">숨김 테스트 파일 업로드</h4>
    <p className="mt-1 text-xs text-violet-800 dark:text-violet-200">입력과 정답 UTF-8 파일을 모두 선택한 뒤 이 버튼을 직접 누르면 저장 참조가 추가됩니다. 각 파일은 {fileLimit} 이하이며 내용은 업로드 화면에 표시하지 않습니다.</p>
    <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="block">입력 파일<input ref={inputFileRef} aria-label="숨김 테스트 입력 파일" type="file" disabled={uploading || disabled} onChange={event => chooseInput(event.currentTarget.files?.[0] ?? null)} className="mt-1 block w-full text-xs" /></label><label className="block">정답 파일<input ref={expectedOutputFileRef} aria-label="숨김 테스트 정답 파일" type="file" disabled={uploading || disabled} onChange={event => chooseExpectedOutput(event.currentTarget.files?.[0] ?? null)} className="mt-1 block w-full text-xs" /></label></div>
    {error && <p role="alert" className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-100">{error}</p>}
    {notice && <p role="status" className="mt-3 rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">{notice}</p>}
    <div className="mt-3 flex justify-end"><button type="button" disabled={uploading || disabled || !inputFile || !expectedOutputFile} onClick={() => void upload()} className="inline-flex items-center gap-1 rounded bg-violet-700 px-3 py-2 text-sm font-semibold text-white hover:bg-violet-800 disabled:opacity-50">{uploading ? <Loader2 size={15} className="animate-spin" /> : <FileUp size={15} />} {uploading ? '업로드 중...' : '숨김 테스트 업로드'}</button></div>
  </section>;
}
