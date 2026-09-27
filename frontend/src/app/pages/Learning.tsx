import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Link, useNavigate } from 'react-router';
import { AlertCircle, Bookmark, BookOpenCheck, CheckCircle2, ChevronRight, CircleDashed, Code2, Lightbulb, Loader2, RefreshCw, Tag } from 'lucide-react';
import { ProblemReviewControls } from '../components/ProblemReviewControls';
import { DIFFICULTY_LABELS, getDifficultyBadgeClass } from '../constants/difficulty';
import { getProblemTagClass, getProblemTagLabel } from '../constants/problemTags';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import {
  getLearningRecommendations,
  getLearningReview,
  getLearningTrack,
  getLearningTracks,
  type LearningProblem,
  type LearningRecommendationsResponse,
  type LearningReviewFilter,
  type LearningTrack,
} from '../services/learningApi';
import { getProblem } from '../services/problemApi';

type LearningTab = 'tracks' | 'review' | 'recommendations';

const PAGE_SIZE = 24;

function getAuthScope(): string {
  if (typeof window === 'undefined') return 'guest';
  const token = window.localStorage.getItem('authToken');
  return token ? `${getAuthOwner()}:${token}` : 'guest';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

function ProblemCard({
  item,
  onOpen,
  opening,
  showPrivate,
  onReview,
}: {
  item: LearningProblem;
  onOpen: (id: string) => void;
  opening: boolean;
  showPrivate: boolean;
  onReview?: (id: string) => void;
}) {
  const status = item.solved ? '해결' : item.attempted ? '시도함' : '미시도';
  const StatusIcon = item.solved ? CheckCircle2 : CircleDashed;
  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-[#333] dark:bg-[#161616] sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${getDifficultyBadgeClass(item.difficulty)}`}>
              {DIFFICULTY_LABELS[item.difficulty as keyof typeof DIFFICULTY_LABELS] ?? item.difficulty}
            </span>
            <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium ${item.solved ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : item.attempted ? 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300' : 'border-gray-300 bg-gray-50 text-gray-600 dark:border-[#444] dark:bg-[#111] dark:text-gray-400'}`}>
              <StatusIcon size={12} /> {status}
            </span>
            {item.bookmarked && <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-600 dark:text-amber-300"><Bookmark size={14} className="fill-current" /> 북마크</span>}
          </div>
          <h3 className="mt-3 break-words text-base font-bold text-gray-900 dark:text-white">{item.title}</h3>
        </div>
        <button type="button" disabled={opening} onClick={() => onOpen(item.id)} className="inline-flex shrink-0 items-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50">
          {opening ? <Loader2 size={15} className="animate-spin" /> : <Code2 size={15} />} 문제 풀기
        </button>
      </div>

      {(item.tags ?? []).length > 0 && <div className="mt-3 flex flex-wrap gap-1.5" aria-label="문제 태그">
        {item.tags.map(tag => <span key={tag} className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${getProblemTagClass(tag)}`}><Tag size={11} /> {getProblemTagLabel(tag)}</span>)}
      </div>}

      {item.reason && <p className="mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-950 dark:border-blue-500/30 dark:bg-blue-950/20 dark:text-blue-100"><span className="font-semibold">추천 근거: </span>{item.reason}</p>}
      {showPrivate && item.note && <p className="mt-3 whitespace-pre-wrap break-words rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-700 dark:bg-[#101010] dark:text-gray-300"><span className="font-semibold">내 메모: </span>{item.note}</p>}

      {onReview && <button type="button" onClick={() => onReview(item.id)} className="mt-4 text-sm font-semibold text-blue-600 hover:underline dark:text-blue-300">복습 메모 {showPrivate ? '열기' : '관리'}</button>}
    </article>
  );
}

export function Learning() {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  return <LearningForScope key={scope} scope={scope} />;
}

function LearningForScope({ scope }: { scope: string }) {
  const navigate = useNavigate();
  const signedIn = scope !== 'guest';
  const [serverSignedIn, setServerSignedIn] = useState<boolean | null>(null);
  const canUsePrivate = signedIn && serverSignedIn !== false;
  const [tab, setTab] = useState<LearningTab>('tracks');
  const [tracks, setTracks] = useState<LearningTrack[]>([]);
  const [tracksLoading, setTracksLoading] = useState(true);
  const [tracksError, setTracksError] = useState('');
  const [tracksRetry, setTracksRetry] = useState(0);
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(null);
  const [trackItems, setTrackItems] = useState<LearningProblem[]>([]);
  const [trackItemsTrackId, setTrackItemsTrackId] = useState<string | null>(null);
  const [trackTotal, setTrackTotal] = useState(0);
  const [trackLoading, setTrackLoading] = useState(false);
  const [trackError, setTrackError] = useState('');
  const [trackRetry, setTrackRetry] = useState(0);
  const [reviewFilter, setReviewFilter] = useState<LearningReviewFilter>('unresolved');
  const [reviewItems, setReviewItems] = useState<LearningProblem[]>([]);
  const [reviewItemsKey, setReviewItemsKey] = useState<string | null>(null);
  const [reviewTotal, setReviewTotal] = useState(0);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState('');
  const [reviewRetry, setReviewRetry] = useState(0);
  const [recommendations, setRecommendations] = useState<LearningRecommendationsResponse | null>(null);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [recommendationsError, setRecommendationsError] = useState('');
  const [recommendationsRetry, setRecommendationsRetry] = useState(0);
  const [reviewEditorId, setReviewEditorId] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [openError, setOpenError] = useState('');
  const mountedRef = useRef(false);
  const tracksRequestRef = useRef<AbortController | null>(null);
  const trackRequestRef = useRef<AbortController | null>(null);
  const reviewRequestRef = useRef<AbortController | null>(null);
  const recommendationsRequestRef = useRef<AbortController | null>(null);

  const currentScope = () => mountedRef.current && getAuthScope() === scope;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      tracksRequestRef.current?.abort();
      trackRequestRef.current?.abort();
      reviewRequestRef.current?.abort();
      recommendationsRequestRef.current?.abort();
    };
  }, [scope]);

  useEffect(() => {
    const controller = new AbortController();
    tracksRequestRef.current?.abort();
    tracksRequestRef.current = controller;
    setTracksLoading(true);
    setTracksError('');
    void getLearningTracks(controller.signal).then(response => {
      if (!currentScope() || tracksRequestRef.current !== controller) return;
      setTracks(response.tracks);
      setServerSignedIn(response.signedIn);
      setSelectedTrackId(current => response.tracks.some(track => track.id === current) ? current : (response.tracks[0]?.id ?? null));
    }).catch(error => {
      if (!currentScope() || tracksRequestRef.current !== controller || isAbort(error)) return;
      setTracksError(error instanceof Error ? error.message : '문제집을 불러오지 못했습니다.');
      setTracks([]);
    }).finally(() => {
      if (currentScope() && tracksRequestRef.current === controller) setTracksLoading(false);
    });
    return () => controller.abort();
    // A scope change remounts this component and aborts its old request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, tracksRetry]);

  const requestTrackPage = async (offset: number, append: boolean) => {
    if (!selectedTrackId) return;
    const requestedTrackId = selectedTrackId;
    const controller = new AbortController();
    trackRequestRef.current?.abort();
    trackRequestRef.current = controller;
    setTrackLoading(true);
    setTrackError('');
    if (!append) {
      setTrackItemsTrackId(null);
      setTrackItems([]);
      setTrackTotal(0);
    }
    try {
      const page = await getLearningTrack(requestedTrackId, PAGE_SIZE, offset, controller.signal);
      if (!currentScope() || trackRequestRef.current !== controller) return;
      setTrackTotal(page.total);
      setTrackItemsTrackId(requestedTrackId);
      setTrackItems(current => append ? [...current, ...page.items.filter(item => !current.some(existing => existing.id === item.id))] : page.items);
    } catch (error) {
      if (!currentScope() || trackRequestRef.current !== controller || isAbort(error)) return;
      setTrackError(error instanceof Error ? error.message : '문제집 문제를 불러오지 못했습니다.');
      if (!append) {
        setTrackItemsTrackId(requestedTrackId);
        setTrackItems([]);
      }
    } finally {
      if (currentScope() && trackRequestRef.current === controller) setTrackLoading(false);
    }
  };

  useEffect(() => {
    if (tab !== 'tracks' || !selectedTrackId) return;
    void requestTrackPage(0, false);
    return () => trackRequestRef.current?.abort();
    // The selected id and scope are request fences; a stale page cannot append.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, selectedTrackId, scope, trackRetry]);

  const requestReviewPage = async (offset: number, append: boolean) => {
    if (!canUsePrivate) return;
    const requestedReviewKey = `${scope}:${reviewFilter}`;
    const controller = new AbortController();
    reviewRequestRef.current?.abort();
    reviewRequestRef.current = controller;
    setReviewLoading(true);
    setReviewError('');
    if (!append) {
      setReviewItemsKey(null);
      setReviewItems([]);
      setReviewTotal(0);
    }
    try {
      const page = await getLearningReview(reviewFilter, PAGE_SIZE, offset, controller.signal);
      if (!currentScope() || reviewRequestRef.current !== controller) return;
      setReviewTotal(page.total);
      setReviewItemsKey(requestedReviewKey);
      setReviewItems(current => append ? [...current, ...page.items.filter(item => !current.some(existing => existing.id === item.id))] : page.items);
    } catch (error) {
      if (!currentScope() || reviewRequestRef.current !== controller || isAbort(error)) return;
      setReviewError(error instanceof Error ? error.message : '복습 목록을 불러오지 못했습니다.');
      if (!append) {
        setReviewItemsKey(requestedReviewKey);
        setReviewItems([]);
      }
    } finally {
      if (currentScope() && reviewRequestRef.current === controller) setReviewLoading(false);
    }
  };

  useEffect(() => {
    if (tab !== 'review' || !canUsePrivate) return;
    void requestReviewPage(0, false);
    return () => reviewRequestRef.current?.abort();
    // A filter or account scope creates a new, fenced list request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, reviewFilter, scope, canUsePrivate, reviewRetry]);

  useEffect(() => {
    if (tab !== 'recommendations') return;
    const controller = new AbortController();
    recommendationsRequestRef.current?.abort();
    recommendationsRequestRef.current = controller;
    setRecommendationsLoading(true);
    setRecommendationsError('');
    void getLearningRecommendations(controller.signal).then(response => {
      if (!currentScope() || recommendationsRequestRef.current !== controller) return;
      setRecommendations(response);
      setServerSignedIn(response.signedIn);
    }).catch(error => {
      if (!currentScope() || recommendationsRequestRef.current !== controller || isAbort(error)) return;
      setRecommendationsError(error instanceof Error ? error.message : '추천 문제를 불러오지 못했습니다.');
      setRecommendations(null);
    }).finally(() => {
      if (currentScope() && recommendationsRequestRef.current === controller) setRecommendationsLoading(false);
    });
    return () => controller.abort();
    // Scope remounts, so a response for a former account is discarded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, scope, recommendationsRetry]);

  const openProblem = async (problemId: string) => {
    if (openingId || !currentScope()) return;
    setOpeningId(problemId);
    setOpenError('');
    try {
      const challenge = await getProblem(problemId);
      if (!currentScope()) return;
      navigate('/ide', { state: { challenge } });
    } catch (error) {
      if (currentScope()) setOpenError(error instanceof Error ? error.message : '문제를 열지 못했습니다.');
    } finally {
      if (currentScope()) setOpeningId(null);
    }
  };

  const selectedTrack = tracks.find(track => track.id === selectedTrackId) ?? null;
  const visibleTrackItems = trackItemsTrackId === selectedTrackId ? trackItems : [];
  const currentReviewKey = `${scope}:${reviewFilter}`;
  const visibleReviewItems = reviewItemsKey === currentReviewKey ? reviewItems : [];
  const tabs: Array<{ id: LearningTab; label: string; icon: typeof BookOpenCheck }> = [
    { id: 'tracks', label: '문제집', icon: BookOpenCheck },
    { id: 'review', label: '복습', icon: CheckCircle2 },
    { id: 'recommendations', label: '추천', icon: Lightbulb },
  ];

  return (
    <section className="h-full min-h-0 w-full overflow-y-auto bg-gray-50 text-gray-900 dark:bg-[#0d1117] dark:text-white">
      <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-10">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-bold sm:text-3xl">학습</h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">문제집으로 순서대로 풀고, 다시 볼 문제와 다음 문제를 정리하세요.</p>
        </div>

        <div role="tablist" aria-label="학습 메뉴" className="mt-6 flex w-full gap-1 overflow-x-auto rounded-xl border border-gray-200 bg-white p-1 dark:border-[#333] dark:bg-[#161616] sm:w-fit">
          {tabs.map(({ id, label, icon: Icon }) => <button key={id} role="tab" type="button" aria-selected={tab === id} onClick={() => { setTab(id); setReviewEditorId(null); }} className={`inline-flex shrink-0 items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${tab === id ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-[#252525]'}`}><Icon size={16} /> {label}</button>)}
        </div>

        {openError && <div role="alert" className="mt-5 flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/20 dark:text-red-200"><AlertCircle size={17} className="mt-0.5 shrink-0" /> {openError}</div>}

        {tab === 'tracks' && <section className="mt-6" aria-labelledby="tracks-heading">
          <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="tracks-heading" className="text-xl font-bold">문제집</h2>{!tracksLoading && <span className="text-sm text-gray-500 dark:text-gray-400">{tracks.length}개 과정</span>}</div>
          {tracksLoading ? <LoadingState label="문제집을 불러오는 중..." /> : tracksError ? <ErrorState message={tracksError} onRetry={() => setTracksRetry(value => value + 1)} /> : tracks.length === 0 ? <EmptyState title="등록된 문제집이 없습니다" detail="현재 시작할 수 있는 문제집이 없습니다." /> : <>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {tracks.map(track => {
                const active = selectedTrackId === track.id;
                const progress = track.total > 0 ? Math.round((track.solved / track.total) * 100) : 0;
                return <button key={track.id} type="button" onClick={() => { setSelectedTrackId(track.id); setTrackItemsTrackId(null); setTrackItems([]); setTrackTotal(0); setTrackError(''); setTrackRetry(value => value + 1); }} className={`rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-blue-500 ${active ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/20' : 'border-gray-200 bg-white hover:border-blue-300 dark:border-[#333] dark:bg-[#161616]'}`}>
                  <div className="flex items-start justify-between gap-3"><span className="text-xs font-semibold text-gray-500 dark:text-gray-400">과정 {track.order}</span><ChevronRight size={17} className="shrink-0 text-gray-400" /></div>
                  <h3 className="mt-2 break-words font-bold">{track.title}</h3>
                  <p className="mt-1 line-clamp-2 text-sm text-gray-600 dark:text-gray-300">{track.description}</p>
                  <div className="mt-4"><div className="flex justify-between text-xs text-gray-500 dark:text-gray-400"><span>진행도</span><span>{track.solved}/{track.total}</span></div><div className="mt-1.5 h-2 overflow-hidden rounded-full bg-gray-200 dark:bg-[#333]"><div className="h-full rounded-full bg-blue-600" style={{ width: `${progress}%` }} /></div></div>
                </button>;
              })}
            </div>
            {selectedTrack && <section className="mt-8" aria-labelledby="track-problems-heading">
              <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 id="track-problems-heading" className="text-lg font-bold">{selectedTrack.title}</h2><p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{trackTotal}문제</p></div>{selectedTrack.nextProblemId && <button type="button" disabled={openingId !== null} onClick={() => void openProblem(selectedTrack.nextProblemId!)} className="inline-flex items-center gap-1 rounded-md border border-blue-300 px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50 dark:border-blue-500/40 dark:text-blue-300 dark:hover:bg-blue-950/20">다음 문제 풀기 <ChevronRight size={16} /></button>}</div>
              {trackLoading && visibleTrackItems.length === 0 ? <LoadingState label="문제집 문제를 불러오는 중..." /> : trackError ? <ErrorState message={trackError} onRetry={() => setTrackRetry(value => value + 1)} /> : visibleTrackItems.length === 0 ? <EmptyState title="표시할 문제가 없습니다" detail="이 문제집의 문제를 아직 준비 중입니다." /> : <div className="mt-4 grid gap-4 lg:grid-cols-2">{visibleTrackItems.map(item => <ProblemCard key={item.id} item={item} onOpen={id => void openProblem(id)} opening={openingId === item.id} showPrivate={canUsePrivate} />)}</div>}
              {!trackLoading && !trackError && visibleTrackItems.length < trackTotal && <LoadMore onClick={() => void requestTrackPage(visibleTrackItems.length, true)} label={`문제 더 보기 (${visibleTrackItems.length}/${trackTotal})`} />}
              {trackLoading && visibleTrackItems.length > 0 && <p role="status" className="mt-4 inline-flex items-center gap-2 text-sm text-gray-500"><Loader2 size={15} className="animate-spin" /> 더 불러오는 중...</p>}
            </section>}
          </>}
        </section>}

        {tab === 'review' && <section className="mt-6" aria-labelledby="review-heading">
          <h2 id="review-heading" className="text-xl font-bold">복습</h2>
          {!canUsePrivate ? <LoginGuidance /> : <>
            <div className="mt-4 flex flex-wrap gap-2" aria-label="복습 필터">
              {([['unresolved', '미해결'], ['bookmarked', '북마크'], ['notes', '메모 있음'], ['all', '전체']] as Array<[LearningReviewFilter, string]>).map(([value, label]) => <button key={value} type="button" onClick={() => {
                if (value === reviewFilter) return;
                setReviewFilter(value);
                setReviewItemsKey(null);
                setReviewItems([]);
                setReviewTotal(0);
                setReviewError('');
                setReviewEditorId(null);
              }} className={`rounded-full border px-3 py-1.5 text-sm font-semibold ${reviewFilter === value ? 'border-blue-600 bg-blue-600 text-white' : 'border-gray-300 bg-white text-gray-700 hover:border-blue-400 dark:border-[#444] dark:bg-[#161616] dark:text-gray-200'}`}>{label}</button>)}
            </div>
            {reviewLoading && visibleReviewItems.length === 0 ? <LoadingState label="복습 목록을 불러오는 중..." /> : reviewError ? <ErrorState message={reviewError} onRetry={() => setReviewRetry(value => value + 1)} /> : visibleReviewItems.length === 0 ? <EmptyState title="복습할 문제가 없습니다" detail="다른 필터를 선택하거나 문제를 풀어보세요." /> : <div className="mt-5 space-y-4">{visibleReviewItems.map(item => <div key={item.id}><ProblemCard item={item} onOpen={id => void openProblem(id)} opening={openingId === item.id} showPrivate onReview={setReviewEditorId} />{reviewEditorId === item.id && <div className="mt-3"><ProblemReviewControls problemId={item.id} onSaved={() => setReviewRetry(value => value + 1)} /></div>}</div>)}</div>}
            {!reviewLoading && !reviewError && visibleReviewItems.length < reviewTotal && <LoadMore onClick={() => void requestReviewPage(visibleReviewItems.length, true)} label={`문제 더 보기 (${visibleReviewItems.length}/${reviewTotal})`} />}
            {reviewLoading && visibleReviewItems.length > 0 && <p role="status" className="mt-4 inline-flex items-center gap-2 text-sm text-gray-500"><Loader2 size={15} className="animate-spin" /> 더 불러오는 중...</p>}
          </>}
        </section>}

        {tab === 'recommendations' && <section className="mt-6" aria-labelledby="recommendations-heading">
          <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 id="recommendations-heading" className="text-xl font-bold">추천</h2><p className="mt-1 text-sm text-gray-600 dark:text-gray-300">추천 규칙과 근거가 제공된 문제만 보여줍니다.</p></div>{recommendations && <span className="rounded-full border border-blue-300 bg-blue-50 px-3 py-1 text-sm font-semibold text-blue-800 dark:border-blue-500/30 dark:bg-blue-950/20 dark:text-blue-200">목표 난이도: {DIFFICULTY_LABELS[recommendations.targetDifficulty as keyof typeof DIFFICULTY_LABELS] ?? recommendations.targetDifficulty}</span>}</div>
          {recommendationsLoading ? <LoadingState label="추천 문제를 불러오는 중..." /> : recommendationsError ? <ErrorState message={recommendationsError} onRetry={() => setRecommendationsRetry(value => value + 1)} /> : !recommendations || recommendations.items.length === 0 ? <EmptyState title="추천할 문제가 없습니다" detail="추천 기준에 맞는 문제가 생기면 여기에서 확인할 수 있습니다." /> : <div className="mt-5 grid gap-4 lg:grid-cols-2">{recommendations.items.map(item => <ProblemCard key={item.id} item={item} onOpen={id => void openProblem(id)} opening={openingId === item.id} showPrivate={canUsePrivate} />)}</div>}
        </section>}
      </div>
    </section>
  );
}

function LoadingState({ label }: { label: string }) {
  return <div role="status" className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-gray-500 dark:text-gray-400"><Loader2 size={28} className="animate-spin text-blue-500" /> {label}</div>;
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div role="alert" className="mt-5 rounded-xl border border-red-300 bg-red-50 p-5 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/20 dark:text-red-200"><div className="flex items-start gap-2"><AlertCircle size={18} className="mt-0.5 shrink-0" /> <span>{message}</span></div><button type="button" onClick={onRetry} className="mt-3 inline-flex items-center gap-1 font-semibold underline"><RefreshCw size={14} /> 다시 시도</button></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="mt-5 rounded-xl border border-dashed border-gray-300 bg-white px-5 py-14 text-center dark:border-[#444] dark:bg-[#161616]"><h3 className="font-bold">{title}</h3><p className="mt-2 text-sm text-gray-500 dark:text-gray-400">{detail}</p></div>;
}

function LoadMore({ onClick, label }: { onClick: () => void; label: string }) {
  return <div className="mt-5 text-center"><button type="button" onClick={onClick} className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:border-blue-400 dark:border-[#444] dark:bg-[#161616] dark:text-gray-200">{label}</button></div>;
}

function LoginGuidance() {
  return <div className="mt-5 rounded-xl border border-gray-200 bg-white p-5 text-sm dark:border-[#333] dark:bg-[#161616]"><p className="text-gray-700 dark:text-gray-300">복습 목록과 개인 메모는 로그인한 계정에서만 볼 수 있습니다.</p><Link to="/settings" className="mt-3 inline-flex font-semibold text-blue-600 hover:underline dark:text-blue-300">로그인하러 가기</Link></div>;
}
