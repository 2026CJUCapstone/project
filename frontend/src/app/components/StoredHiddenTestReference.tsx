import type { StoredHiddenTestCase } from '../services/problemApi';

export interface StoredHiddenTestReferenceProps {
  testCase: StoredHiddenTestCase;
  ordinal: number;
  label: string;
  canRemove?: boolean;
  onRemove?: () => void;
}

/** Displays a server-side hidden-test reference without requesting its contents. */
export function StoredHiddenTestReference({ testCase, ordinal, label, canRemove = false, onRemove }: StoredHiddenTestReferenceProps) {
  return <div className="min-w-0 rounded border border-violet-300 bg-violet-50 p-3 text-sm text-violet-950 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-100" data-testid="stored-hidden-test-reference">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><strong>{label} {ordinal} · 저장 참조</strong><p className="mt-1 text-xs text-violet-800 dark:text-violet-200">읽기 전용 참조입니다. 테스트 내용은 이 화면에서 내려받거나 편집하지 않습니다.</p></div>{canRemove && onRemove && <button type="button" onClick={onRemove} aria-label={`${label} ${ordinal} 삭제`} className="text-red-600 hover:text-red-800 dark:text-red-300">삭제</button>}</div>
    <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2"><div><dt className="font-semibold">입력 참조</dt><dd className="mt-1 break-all font-mono">{testCase.inputRef.digest}</dd><dd>{testCase.inputRef.byteCount.toLocaleString('ko-KR')} bytes · {testCase.inputRef.encoding}</dd></div><div><dt className="font-semibold">기대 출력 참조</dt><dd className="mt-1 break-all font-mono">{testCase.expectedOutputRef.digest}</dd><dd>{testCase.expectedOutputRef.byteCount.toLocaleString('ko-KR')} bytes · {testCase.expectedOutputRef.encoding}</dd></div></dl>
  </div>;
}
