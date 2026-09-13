import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Link } from 'react-router';
import { Bookmark, CheckCircle2, Loader2, RefreshCw, Save } from 'lucide-react';
import { ApiError } from '../services/apiBase';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import {
  getLearningProblemReview,
  updateLearningProblemReview,
  type LearningProblemReview,
} from '../services/learningApi';

interface ReviewDraft {
  bookmarked: boolean;
  note: string;
  reviewed: boolean;
}

function getAuthScope(): string {
  if (typeof window === 'undefined') return 'guest';
  const token = window.localStorage.getItem('authToken');
  return token ? `${getAuthOwner()}:${token}` : 'guest';
}

function draftFrom(record: LearningProblemReview): ReviewDraft {
  return {
    bookmarked: record.bookmarked,
    note: record.note ?? '',
    reviewed: record.reviewed ?? record.reviewedAt !== null,
  };
}

export function ProblemReviewControls({ problemId, onSaved }: { problemId: string; onSaved?: (record: LearningProblemReview) => void }) {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  return <ProblemReviewControlsForScope key={`${scope}:${problemId}`} problemId={problemId} scope={scope} onSaved={onSaved} />;
}

function ProblemReviewControlsForScope({ problemId, scope, onSaved }: { problemId: string; scope: string; onSaved?: (record: LearningProblemReview) => void }) {
  const signedIn = scope !== 'guest';
  const [record, setRecord] = useState<LearningProblemReview | null>(null);
  const [draft, setDraft] = useState<ReviewDraft>({ bookmarked: false, note: '', reviewed: false });
  const [loading, setLoading] = useState(signedIn);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState(false);
  const [hasConflict, setHasConflict] = useState(false);
  const mountedRef = useRef(false);
  const savingRef = useRef(false);
  const loadControllerRef = useRef<AbortController | null>(null);
  const saveControllerRef = useRef<AbortController | null>(null);

  const currentScope = () => mountedRef.current && getAuthScope() === scope;

  const loadReview = async (preserveDraft: boolean) => {
    if (!signedIn) return;
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    setLoading(true);
    setLoadError('');
    try {
      const nextRecord = await getLearningProblemReview(problemId, controller.signal);
      if (!currentScope() || loadControllerRef.current !== controller) return;
      setRecord(nextRecord);
      if (!preserveDraft) setDraft(draftFrom(nextRecord));
      setHasConflict(false);
      if (preserveDraft) setSaveError('서버의 최신 버전을 확인했습니다. 작성 중인 메모는 바꾸지 않았습니다.');
    } catch (error) {
      if (!currentScope() || loadControllerRef.current !== controller || (error instanceof DOMException && error.name === 'AbortError')) return;
      setLoadError(error instanceof Error ? error.message : '복습 정보를 불러오지 못했습니다.');
    } finally {
      if (currentScope() && loadControllerRef.current === controller) setLoading(false);
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    void loadReview(false);
    return () => {
      mountedRef.current = false;
      loadControllerRef.current?.abort();
      saveControllerRef.current?.abort();
    };
    // The keyed scope intentionally owns every request and unsaved draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [problemId, scope]);

  const saveReview = async () => {
    if (!record || saving || savingRef.current || !signedIn) return;
    if (draft.note.length > 5000) {
      setSaveError('메모는 5,000자까지 저장할 수 있습니다.');
      return;
    }
    if (!currentScope()) return;

    savingRef.current = true;
    saveControllerRef.current?.abort();
    const controller = new AbortController();
    saveControllerRef.current = controller;
    setSaving(true);
    setSaved(false);
    setSaveError('');
    try {
      const savedRecord = await updateLearningProblemReview(problemId, {
        bookmarked: draft.bookmarked,
        note: draft.note,
        reviewed: draft.reviewed,
        version: record.version,
      }, controller.signal);
      if (!currentScope() || saveControllerRef.current !== controller) return;
      setRecord(savedRecord);
      setDraft(draftFrom(savedRecord));
      setHasConflict(false);
      setSaved(true);
      onSaved?.(savedRecord);
    } catch (error) {
      if (!currentScope() || saveControllerRef.current !== controller || (error instanceof DOMException && error.name === 'AbortError')) return;
      if (error instanceof ApiError && error.status === 409) {
        setHasConflict(true);
        setSaveError('다른 곳에서 복습 정보가 바뀌었습니다. 작성 중인 메모는 보존했으니 최신 버전을 먼저 확인해 주세요.');
      } else {
        setSaveError(error instanceof Error ? error.message : '복습 정보를 저장하지 못했습니다.');
      }
    } finally {
      if (saveControllerRef.current === controller) {
        savingRef.current = false;
        if (currentScope()) setSaving(false);
      }
    }
  };

  if (!signedIn) {
    return (
      <section aria-label="복습 메모" className="rounded-xl border border-gray-200 bg-white p-4 text-sm dark:border-[#333] dark:bg-[#161616]">
        <p className="text-gray-600 dark:text-gray-300">북마크와 개인 메모는 로그인 후 저장할 수 있습니다.</p>
        <Link to="/settings" className="mt-3 inline-flex text-sm font-semibold text-blue-600 hover:underline dark:text-blue-300">로그인하러 가기</Link>
      </section>
    );
  }

  if (loading && !record) {
    return <p role="status" className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400"><Loader2 size={16} className="animate-spin" /> 복습 정보를 불러오는 중...</p>;
  }

  if (!record) {
    return (
      <section aria-label="복습 메모" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950/20">
        <p role="alert">{loadError || '복습 정보를 불러오지 못했습니다.'}</p>
        <button type="button" onClick={() => void loadReview(false)} className="mt-3 inline-flex items-center gap-1 text-blue-700 underline dark:text-blue-300"><RefreshCw size={14} /> 다시 시도</button>
      </section>
    );
  }

  return (
    <section aria-labelledby={`review-controls-${problemId}`} className="rounded-xl border border-gray-200 bg-white p-4 dark:border-[#333] dark:bg-[#161616] sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 id={`review-controls-${problemId}`} className="font-bold text-gray-900 dark:text-white">복습 메모</h3>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">이 메모는 내 계정에서만 볼 수 있습니다.</p>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium">
          <input
            aria-label="북마크"
            type="checkbox"
            checked={draft.bookmarked}
            disabled={saving}
            onChange={event => { setDraft(value => ({ ...value, bookmarked: event.target.checked })); setSaved(false); }}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 disabled:cursor-not-allowed"
          />
          <Bookmark size={15} className={draft.bookmarked ? 'fill-current text-amber-500' : 'text-gray-500'} /> 북마크
        </label>
      </div>

      <label className="mt-4 block">
        <span className="sr-only">개인 메모</span>
        <textarea
          aria-label="개인 메모"
          value={draft.note}
          maxLength={5000}
          rows={5}
          disabled={saving}
          onChange={event => { setDraft(value => ({ ...value, note: event.target.value })); setSaved(false); }}
          placeholder="다음에 다시 풀 때 참고할 내용을 적어보세요."
          className="w-full resize-y rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:cursor-not-allowed disabled:opacity-70 dark:border-[#444] dark:bg-[#111]"
        />
        <span className="mt-1 block text-right text-xs text-gray-500 dark:text-gray-400">{draft.note.length.toLocaleString()}/5,000</span>
      </label>

      <label className="mt-3 flex cursor-pointer items-center gap-2 text-sm">
        <input
          aria-label="복습 완료"
          type="checkbox"
          checked={draft.reviewed}
          disabled={saving}
          onChange={event => { setDraft(value => ({ ...value, reviewed: event.target.checked })); setSaved(false); }}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 disabled:cursor-not-allowed"
        />
        <CheckCircle2 size={16} className={draft.reviewed ? 'text-emerald-500' : 'text-gray-500'} /> 복습 완료로 표시
      </label>

      {loadError && <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-300">{loadError}</p>}
      {saveError && <p role="alert" className={hasConflict ? 'mt-3 text-sm text-amber-700 dark:text-amber-300' : 'mt-3 text-sm text-red-600 dark:text-red-300'}>{saveError}</p>}
      {saved && <p role="status" className="mt-3 text-sm text-emerald-700 dark:text-emerald-300">저장했습니다.</p>}

      <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
        {hasConflict && <button type="button" disabled={loading || saving} onClick={() => void loadReview(true)} className="inline-flex items-center gap-1 rounded-md border border-amber-400 px-3 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-50 disabled:opacity-50 dark:text-amber-200 dark:hover:bg-amber-950/30"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> 최신 버전 확인</button>}
        <button type="button" disabled={saving || loading} onClick={() => void saveReview()} className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"><Save size={15} /> {saving ? '저장 중...' : '저장'}</button>
      </div>
    </section>
  );
}
