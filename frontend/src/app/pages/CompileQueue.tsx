import { Fragment, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import {
  Activity,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Cpu,
  Filter,
  Layers3,
  RefreshCw,
  RotateCcw,
  Timer,
  UserRound,
  XCircle,
} from 'lucide-react';
import { useSearchParams } from 'react-router';
import {
  getCompileQueue,
  type CompileQueueFilters,
  type CompileQueueGroup,
  type CompileQueueJob,
  type CompileQueueKind,
  type CompileQueueContestOption,
  type CompileQueueProblemOption,
  type CompileQueueSource,
  type CompileQueueStatus,
  type CompileQueueVerdict,
  type CompilerLanguage,
} from '../services/compilerApi';
import { getAuthOwner, subscribeAuthIdentity } from '../services/authIdentity';
import { normalizedPageParam } from '../services/pageQuery';

const PAGE_SIZE = 50;

const controlClassName = 'w-full min-w-0 rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white';

type ProblemContext = { contestId: string | null };

function getAuthScope(): string {
  if (typeof window === 'undefined') return 'guest';
  const token = window.localStorage.getItem('authToken');
  return token && token !== 'undefined' && token !== 'null' ? `${getAuthOwner()}:${token}` : 'guest';
}

const statusLabels: Record<CompileQueueStatus, string> = {
  queued: '대기',
  running: '실행 중',
  completed: '처리됨',
  failed: '시스템 실패',
  canceled: '취소',
};

const kindLabels: Record<CompileQueueKind, string> = {
  compile: '컴파일',
  run: '실행',
  grading: '채점',
};

const verdictLabels: Record<CompileQueueVerdict, string> = {
  pending: '대기',
  running: '실행 중',
  compile_success: '컴파일 성공',
  compile_error: '컴파일 실패',
  accepted: '정답',
  wrong_answer: '오답',
  finished: '정상 종료',
  runtime_error: '런타임 오류',
  time_limit_exceeded: '시간 초과',
  memory_limit_exceeded: '메모리 초과',
  output_limit_exceeded: '출력 초과',
  process_limit_exceeded: '프로세스 제한 초과',
  compile_resource_error: '컴파일 자원 초과',
  system_error: '시스템 오류',
  canceled: '취소',
};

const statusClass: Record<CompileQueueStatus, string> = {
  queued: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  running: 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300',
  completed: 'border-gray-500/30 bg-gray-500/10 text-gray-700 dark:text-gray-300',
  failed: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  canceled: 'border-gray-500/30 bg-gray-500/10 text-gray-700 dark:text-gray-300',
};

const verdictClass: Record<CompileQueueVerdict, string> = {
  pending: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  running: 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300',
  compile_success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  compile_error: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  accepted: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  wrong_answer: 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300',
  finished: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  runtime_error: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  time_limit_exceeded: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  memory_limit_exceeded: 'border-purple-500/30 bg-purple-500/10 text-purple-700 dark:text-purple-300',
  output_limit_exceeded: 'border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-700 dark:text-fuchsia-300',
  process_limit_exceeded: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
  compile_resource_error: 'border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300',
  system_error: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  canceled: 'border-gray-500/30 bg-gray-500/10 text-gray-700 dark:text-gray-300',
};

const verdictPriority: CompileQueueVerdict[] = [
  'running',
  'pending',
  'time_limit_exceeded',
  'memory_limit_exceeded',
  'output_limit_exceeded',
  'process_limit_exceeded',
  'compile_resource_error',
  'compile_error',
  'runtime_error',
  'wrong_answer',
  'system_error',
  'accepted',
  'compile_success',
  'finished',
  'canceled',
];

function formatDate(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '-';
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatDuration(value?: number | null): string {
  if (value === null || value === undefined) return '-';
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

function formatBytes(value?: number | null): string {
  if (value === null || value === undefined) return '-';
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)}MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)}KB`;
  return `${value}B`;
}

function getProblemLabel(job: CompileQueueJob): string {
  return job.problemTitle || job.problemId || '일반 컴파일';
}

function getUsernameLabel(job: CompileQueueJob): string {
  return job.username || '익명';
}

function statusOptions() {
  return [
    { value: 'all', label: '전체 상태' },
    { value: 'queued', label: '대기' },
    { value: 'running', label: '실행 중' },
    { value: 'completed', label: '처리됨' },
    { value: 'failed', label: '시스템 실패' },
    { value: 'canceled', label: '취소' },
  ];
}

function verdictOptions() {
  return [
    { value: 'all', label: '전체 판정' },
    { value: 'accepted', label: '정답' },
    { value: 'wrong_answer', label: '오답' },
    { value: 'compile_error', label: '컴파일 실패' },
    { value: 'runtime_error', label: '런타임 오류' },
    { value: 'time_limit_exceeded', label: '시간 초과' },
    { value: 'memory_limit_exceeded', label: '메모리 초과' },
    { value: 'output_limit_exceeded', label: '출력 초과' },
    { value: 'process_limit_exceeded', label: '프로세스 제한 초과' },
    { value: 'compile_resource_error', label: '컴파일 자원 초과' },
    { value: 'compile_success', label: '컴파일 성공' },
    { value: 'finished', label: '정상 종료' },
    { value: 'pending', label: '대기' },
    { value: 'running', label: '실행 중' },
    { value: 'system_error', label: '시스템 오류' },
    { value: 'canceled', label: '취소' },
  ];
}

function kindOptions() {
  return [
    { value: 'all', label: '전체 작업' },
    { value: 'compile', label: '컴파일' },
    { value: 'run', label: '실행' },
    { value: 'grading', label: '채점' },
  ];
}

function sourceOptions() {
  return [
    { value: 'all', label: '전체 기록' },
    { value: 'ide', label: 'IDE 기록 (공개)' },
    { value: 'practice', label: '연습 기록 (공개)' },
    { value: 'contest', label: '내 대회 기록' },
  ] as const;
}

function languageOptions() {
  return [
    { value: 'all', label: '전체 언어' },
    { value: 'bpp', label: 'B++' },
    { value: 'c', label: 'C' },
    { value: 'cpp', label: 'C++' },
    { value: 'python', label: 'Python' },
    { value: 'java', label: 'Java' },
    { value: 'javascript', label: 'JavaScript' },
  ] as const;
}

function sourceLabel(source?: CompileQueueSource | null): string | null {
  if (source === 'ide') return 'IDE';
  if (source === 'practice') return '연습';
  if (source === 'contest') return '대회';
  return null;
}

function sourceFromQuery(value: string | null): CompileQueueSource | 'all' {
  return value === 'ide' || value === 'practice' || value === 'contest' ? value : 'all';
}

function languageFromQuery(value: string | null): CompilerLanguage | 'all' {
  return value === 'bpp' || value === 'c' || value === 'cpp' || value === 'python' || value === 'java' || value === 'javascript'
    ? value
    : 'all';
}

function problemOptionValue(option: CompileQueueProblemOption): string {
  return JSON.stringify([option.contestId ?? null, option.id]);
}

function primaryVerdict(group: CompileQueueGroup): CompileQueueVerdict {
  return verdictPriority.find((verdict) => (group.verdicts[verdict] || 0) > 0) || 'finished';
}

function GroupTable({
  title,
  icon,
  groups,
  emptyText,
  onPickProblem,
  onPickUser,
  onPickContest,
}: {
  title: string;
  icon: ReactNode;
  groups: CompileQueueGroup[];
  emptyText: string;
  onPickProblem?: (problemId: string, context?: ProblemContext) => void;
  onPickUser?: (username: string) => void;
  onPickContest?: (contestId: string) => void;
}) {
  return (
    <section className="overflow-hidden rounded-md border border-gray-200 bg-white dark:border-[#333] dark:bg-[#1a1a1a]">
      <div className="flex items-center justify-between gap-3 border-b border-gray-200 px-4 py-3 dark:border-[#333]">
        <div className="flex min-w-0 items-center gap-2">
          {icon}
          <h2 className="truncate text-sm font-bold">{title}</h2>
        </div>
        <span className="font-mono text-xs text-gray-500 dark:text-gray-400">{groups.length.toLocaleString()}</span>
      </div>
      <div className="max-h-[320px] overflow-auto">
        {groups.length === 0 ? (
          <div className="px-4 py-6 text-sm text-gray-500 dark:text-gray-400">{emptyText}</div>
        ) : (
          <table className="w-full min-w-[760px] table-fixed text-left text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 text-xs font-semibold text-gray-500 dark:bg-[#151515] dark:text-gray-400">
              <tr>
                <th className="w-[34%] px-4 py-2">이름</th>
                <th className="w-[10%] px-3 py-2 text-right">전체</th>
                <th className="w-[10%] px-3 py-2 text-right">대기</th>
                <th className="w-[10%] px-3 py-2 text-right">실행</th>
                <th className="w-[16%] px-3 py-2">대표 판정</th>
                <th className="w-[20%] px-3 py-2">최근 요청</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-[#282828]">
              {groups.map((group) => {
                const verdict = primaryVerdict(group);
                const canPickProblem = Boolean(group.problemId && onPickProblem);
                const canPickUser = Boolean(group.username && group.username !== '익명' && onPickUser);
                return (
                  <tr key={group.key} className="hover:bg-gray-50 dark:hover:bg-[#202020]">
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        disabled={!canPickProblem && !canPickUser}
                        onClick={() => {
                          if (group.problemId && onPickProblem) {
                            onPickProblem(group.problemId, {
                              contestId: group.contestId ?? null,
                            });
                          }
                          if (group.username && group.username !== '익명' && onPickUser) onPickUser(group.username);
                        }}
                        className="block max-w-full truncate text-left font-semibold text-gray-900 enabled:hover:text-blue-600 disabled:cursor-default dark:text-white dark:enabled:hover:text-blue-300"
                      >
                        {group.label}
                      </button>
                      {(group.problemId || group.userId) && (
                        <p className="mt-0.5 truncate font-mono text-xs text-gray-500 dark:text-gray-500">
                          {group.problemId || group.userId}
                        </p>
                      )}
                      {group.contestId && onPickContest && (
                        <button
                          type="button"
                          onClick={() => onPickContest(group.contestId!)}
                          className="mt-1 inline-flex max-w-full truncate rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-xs font-medium text-violet-700 hover:bg-violet-500/20 dark:text-violet-200"
                        >
                          대회 · {group.contestTitle || group.contestId}
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-gray-700 dark:text-gray-300">{group.total}</td>
                    <td className="px-3 py-3 text-right font-mono text-amber-700 dark:text-amber-300">{group.queued}</td>
                    <td className="px-3 py-3 text-right font-mono text-blue-700 dark:text-blue-300">{group.running}</td>
                    <td className="px-3 py-3">
                      <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-semibold ${verdictClass[verdict]}`}>
                        {verdictLabels[verdict]} {group.verdicts[verdict] || 0}
                      </span>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-gray-600 dark:text-gray-400">
                      {formatDate(group.lastQueuedAt)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

export function CompileQueue() {
  const [searchParams, setSearchParams] = useSearchParams();
  const authScope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  const [jobs, setJobs] = useState<CompileQueueJob[]>([]);
  const [problemGroups, setProblemGroups] = useState<CompileQueueGroup[]>([]);
  const [userGroups, setUserGroups] = useState<CompileQueueGroup[]>([]);
  const [contestOptions, setContestOptions] = useState<CompileQueueContestOption[]>([]);
  const [problemOptions, setProblemOptions] = useState<CompileQueueProblemOption[]>([]);
  const [optionLimit, setOptionLimit] = useState(200);
  const [optionsTruncated, setOptionsTruncated] = useState(false);
  const [queued, setQueued] = useState(0);
  const [running, setRunning] = useState(0);
  const [total, setTotal] = useState(0);
  const [filteredTotal, setFilteredTotal] = useState(0);
  const [resultKey, setResultKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [usernameInput, setUsernameInput] = useState(searchParams.get('username') || '');
  const [problemSearchInput, setProblemSearchInput] = useState(searchParams.get('problemSearch') || '');
  const statusFilter = (searchParams.get('status') || 'all') as CompileQueueStatus | 'all';
  const verdictFilter = (searchParams.get('verdict') || 'all') as CompileQueueVerdict | 'all';
  const kindFilter = (searchParams.get('kind') || 'all') as CompileQueueKind | 'all';
  const sourceFilter = sourceFromQuery(searchParams.get('source'));
  const contestIdFilter = searchParams.get('contestId') || '';
  const problemIdFilter = searchParams.get('problemId') || '';
  const languageFilter = languageFromQuery(searchParams.get('language'));
  const mineFilter = searchParams.get('mine') === 'true';
  const currentPage = normalizedPageParam(searchParams.get('page'), PAGE_SIZE);
  const queryKey = searchParams.toString();
  const requestKey = `${authScope}\u0000${queryKey}`;
  const latestRequestKey = useRef(requestKey);
  const filterGeneration = useRef(0);
  const requestSequence = useRef(0);
  const inFlightRequest = useRef<{ generation: number; requestKey: string; sequence: number } | null>(null);
  if (latestRequestKey.current !== requestKey) {
    latestRequestKey.current = requestKey;
    filterGeneration.current += 1;
  }

  useEffect(() => {
    setUsernameInput(searchParams.get('username') || '');
    setProblemSearchInput(searchParams.get('problemSearch') || '');
  }, [searchParams]);

  const filters = useMemo<CompileQueueFilters>(
    () => ({
      limit: PAGE_SIZE,
      offset: (currentPage - 1) * PAGE_SIZE,
      status: statusFilter,
      verdict: verdictFilter,
      kind: kindFilter,
      username: searchParams.get('username') || undefined,
      problemId: searchParams.get('problemId') || undefined,
      problemSearch: searchParams.get('problemSearch') || undefined,
      source: sourceFilter,
      contestId: contestIdFilter || undefined,
      language: languageFilter,
      mine: mineFilter || undefined,
    }),
    [contestIdFilter, currentPage, kindFilter, languageFilter, mineFilter, searchParams, sourceFilter, statusFilter, verdictFilter],
  );

  const clearQueueResults = useCallback(() => {
    setJobs([]);
    setProblemGroups([]);
    setUserGroups([]);
    setContestOptions([]);
    setProblemOptions([]);
    setQueued(0);
    setRunning(0);
    setTotal(0);
    setFilteredTotal(0);
    setOptionsTruncated(false);
    setResultKey(null);
  }, []);

  const loadQueue = useCallback(async () => {
    const generation = filterGeneration.current;
    const inFlight = inFlightRequest.current;
    if (inFlight?.generation === generation && inFlight.requestKey === requestKey) return;
    const requestAuthScope = getAuthScope();
    const request = { generation, requestKey, sequence: ++requestSequence.current };
    inFlightRequest.current = request;
    const isCurrentRequest = () => (
      generation === filterGeneration.current
      && requestKey === latestRequestKey.current
      && authScope === requestAuthScope
      && getAuthScope() === requestAuthScope
    );
    try {
      setErrorMessage(null);
      const response = await getCompileQueue(filters);
      if (!isCurrentRequest()) return;

      const nextFilteredTotal = response.filteredTotal ?? response.total;
      const responsePages = Math.max(1, Math.ceil(nextFilteredTotal / PAGE_SIZE));
      if (currentPage > responsePages) {
        const next = new URLSearchParams(queryKey);
        if (responsePages <= 1) next.delete('page');
        else next.set('page', String(responsePages));
        setSearchParams(next, { replace: true });
        return;
      }

      setJobs(response.jobs);
      setQueued(response.queued);
      setRunning(response.running);
      setTotal(response.total);
      setFilteredTotal(nextFilteredTotal);
      setProblemGroups(response.problemGroups ?? []);
      setUserGroups(response.userGroups ?? []);
      setContestOptions(response.contestOptions ?? []);
      setProblemOptions(response.problemOptions ?? []);
      setOptionLimit(response.optionLimit ?? 200);
      setOptionsTruncated(Boolean(response.optionsTruncated));
      setResultKey(requestKey);
    } catch (error) {
      if (!isCurrentRequest()) return;
      setErrorMessage(
        authScope === 'guest' && (sourceFilter === 'contest' || Boolean(contestIdFilter) || mineFilter)
          ? '대회 기록과 내 기록은 로그인 후 볼 수 있습니다.'
          : error instanceof Error ? error.message : '컴파일 큐를 불러오지 못했습니다.',
      );
    } finally {
      if (inFlightRequest.current?.sequence === request.sequence) inFlightRequest.current = null;
      if (isCurrentRequest()) setIsLoading(false);
    }
  }, [authScope, contestIdFilter, currentPage, filters, mineFilter, requestKey, setSearchParams, sourceFilter]);

  const startFreshLoad = useCallback(() => {
    clearQueueResults();
    setErrorMessage(null);
    setIsLoading(true);
    void loadQueue();
  }, [clearQueueResults, loadQueue]);

  useEffect(() => {
    startFreshLoad();
    const interval = window.setInterval(() => {
      void loadQueue();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [loadQueue, startFreshLoad]);

  useEffect(() => () => {
    filterGeneration.current += 1;
    inFlightRequest.current = null;
  }, []);

  const hasCurrentResults = resultKey === requestKey;
  const visibleJobs = hasCurrentResults ? jobs : [];
  const visibleProblemGroups = hasCurrentResults ? problemGroups : [];
  const visibleUserGroups = hasCurrentResults ? userGroups : [];
  const visibleContestOptions = hasCurrentResults ? contestOptions : [];
  const visibleProblemOptions = hasCurrentResults ? problemOptions : [];
  const selectedProblemOption = visibleProblemOptions.find((option) => (
    option.id === problemIdFilter && (option.contestId ?? null) === (contestIdFilter || null)
  ));
  const problemSelectionValue = selectedProblemOption
    ? problemOptionValue(selectedProblemOption)
    : problemIdFilter ? `unknown:${problemIdFilter}` : '';
  const visibleQueued = hasCurrentResults ? queued : 0;
  const visibleRunning = hasCurrentResults ? running : 0;
  const visibleTotal = hasCurrentResults ? total : 0;
  const visibleFilteredTotal = hasCurrentResults ? filteredTotal : 0;
  const totalPages = Math.max(1, Math.ceil(visibleFilteredTotal / PAGE_SIZE));

  const updateFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (!value || value === 'all') {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    next.delete('page');
    setSearchParams(next);
  };

  const updateSource = (source: CompileQueueSource | 'all') => {
    const next = new URLSearchParams(searchParams);
    if (source === 'all') next.delete('source');
    else next.set('source', source);
    next.delete('contestId');
    next.delete('problemId');
    next.delete('problemSearch');
    next.delete('page');
    setSearchParams(next);
  };

  const selectContest = (contestId: string) => {
    const next = new URLSearchParams(searchParams);
    next.set('source', 'contest');
    if (contestId) next.set('contestId', contestId);
    else next.delete('contestId');
    next.delete('problemId');
    next.delete('problemSearch');
    next.delete('page');
    setSearchParams(next);
  };

  const selectProblem = (problemId: string, context?: ProblemContext) => {
    const next = new URLSearchParams(searchParams);
    if (problemId) next.set('problemId', problemId);
    else next.delete('problemId');
    if (context?.contestId) {
      next.set('source', 'contest');
      next.set('contestId', context.contestId);
    } else if (context?.contestId === null) {
      next.delete('contestId');
      if (sourceFilter === 'contest') next.delete('source');
    }
    next.delete('page');
    setSearchParams(next);
  };

  const updatePage = (page: number) => {
    const nextPage = Math.min(Math.max(1, page), totalPages);
    const next = new URLSearchParams(searchParams);
    if (nextPage <= 1) next.delete('page');
    else next.set('page', String(nextPage));
    setSearchParams(next);
  };

  const applyTextFilters = () => {
    const next = new URLSearchParams(searchParams);
    const username = usernameInput.trim();
    const problemSearch = problemSearchInput.trim();
    if (username) next.set('username', username);
    else next.delete('username');
    if (problemSearch) next.set('problemSearch', problemSearch);
    else next.delete('problemSearch');
    next.delete('page');
    setSearchParams(next);
  };

  const resetFilters = () => {
    setUsernameInput('');
    setProblemSearchInput('');
    setSearchParams({});
  };

  return (
    <div className="flex h-full w-full min-w-0 flex-col overflow-y-auto bg-gray-50 text-gray-900 transition-colors duration-200 dark:bg-[#121212] dark:text-white lg:overflow-hidden">
      <div className="shrink-0 border-b border-gray-200 bg-white px-4 py-5 transition-colors duration-200 sm:px-6 dark:border-[#333] dark:bg-[#1e1e1e]">
        <div className="mx-auto flex max-w-7xl flex-col gap-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="mb-2 flex items-center gap-3">
                <Activity className="text-blue-600 dark:text-blue-400" size={28} />
                <h1 className="text-2xl font-bold">컴파일 큐</h1>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-gray-600 dark:text-gray-400">
                <span>대기 {visibleQueued.toLocaleString()}</span>
                <span>실행 {visibleRunning.toLocaleString()}</span>
                <span>표시 대상 {visibleFilteredTotal.toLocaleString()}</span>
                <span>보관 {visibleTotal.toLocaleString()}</span>
              </div>
            </div>

            <button
              onClick={startFreshLoad}
              disabled={isLoading}
              className="inline-flex w-fit items-center gap-2 rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]"
            >
              <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
              새로고침
            </button>
          </div>

          <p className="text-xs leading-5 text-gray-600 dark:text-gray-400">
            공개 IDE·연습 기록은 누구나 볼 수 있습니다. 로그인하면 본인의 대회 제출도 함께 볼 수 있으며, 다른 사용자의 대회 제출은 표시되지 않습니다.
          </p>

          <div className="flex flex-wrap items-end gap-3">
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[150px] sm:flex-1 dark:text-gray-300">
              기록 범위
              <select
                aria-label="기록 범위"
                value={sourceFilter}
                onChange={(event) => updateSource(event.target.value as CompileQueueSource | 'all')}
                className={controlClassName}
              >
                {sourceOptions().map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[180px] sm:flex-[1.4] dark:text-gray-300">
              내 대회
              <select
                aria-label="내 대회"
                value={contestIdFilter}
                disabled={visibleContestOptions.length === 0}
                onChange={(event) => selectContest(event.target.value)}
                className={`${controlClassName} disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <option value="">전체 내 대회</option>
                {contestIdFilter && !visibleContestOptions.some((option) => option.id === contestIdFilter) && (
                  <option value={contestIdFilter}>선택된 대회 · {contestIdFilter}</option>
                )}
                {visibleContestOptions.map((option) => (
                  <option key={option.id} value={option.id}>{option.title}</option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[200px] sm:flex-[1.6] dark:text-gray-300">
              문제
              <select
                aria-label="문제"
                value={problemSelectionValue}
                onChange={(event) => {
                  const selected = visibleProblemOptions.find((option) => problemOptionValue(option) === event.target.value);
                  if (selected) selectProblem(selected.id, { contestId: selected.contestId ?? null });
                  else selectProblem('');
                }}
                className={controlClassName}
              >
                <option value="">전체 문제</option>
                {problemIdFilter && !selectedProblemOption && (
                  <option value={problemSelectionValue}>선택된 문제 · {problemIdFilter}</option>
                )}
                {visibleProblemOptions.map((option) => (
                  <option key={problemOptionValue(option)} value={problemOptionValue(option)}>
                    {option.title} · {option.id}{option.contestId ? ' (대회)' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[140px] sm:flex-1 dark:text-gray-300">
              언어
              <select
                aria-label="언어"
                value={languageFilter}
                onChange={(event) => updateFilter('language', event.target.value)}
                className={controlClassName}
              >
                {languageOptions().map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[140px] sm:flex-1 dark:text-gray-300">
              상태
              <select
                aria-label="상태"
                value={statusFilter}
                onChange={(event) => updateFilter('status', event.target.value)}
                className={controlClassName}
              >
                {statusOptions().map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[140px] sm:flex-1 dark:text-gray-300">
              작업
              <select
                aria-label="작업 종류"
                value={kindFilter}
                onChange={(event) => updateFilter('kind', event.target.value)}
                className={controlClassName}
              >
                {kindOptions().map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[150px] sm:flex-1 dark:text-gray-300">
              판정
              <select
                aria-label="판정"
                value={verdictFilter}
                onChange={(event) => updateFilter('verdict', event.target.value)}
                className={controlClassName}
              >
                {verdictOptions().map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[200px] sm:flex-[1.5] dark:text-gray-300">
              문제 제목 또는 ID 검색
              <input
                aria-label="문제 제목 또는 ID 검색"
                value={problemSearchInput}
                onChange={(event) => setProblemSearchInput(event.target.value)}
                className={controlClassName}
                placeholder="제목 또는 ID 일부"
              />
            </label>
            <label className="flex w-full min-w-0 flex-none flex-col gap-1 text-xs font-medium text-gray-600 sm:w-auto sm:min-w-[160px] sm:flex-1 dark:text-gray-300">
              사용자 이름
              <input
                aria-label="사용자 이름"
                value={usernameInput}
                onChange={(event) => setUsernameInput(event.target.value)}
                className={controlClassName}
                placeholder="사용자 이름"
              />
            </label>
            <label className="inline-flex min-h-10 items-center gap-2 rounded-md border border-gray-200 bg-white px-3 text-sm font-medium text-gray-700 dark:border-[#333] dark:bg-[#141414] dark:text-gray-200">
              <input
                aria-label="내 기록만 보기"
                type="checkbox"
                checked={mineFilter}
                onChange={(event) => updateFilter('mine', event.target.checked ? 'true' : '')}
              />
              내 기록만
            </label>
            <button
              type="button"
              onClick={applyTextFilters}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
            >
              <Filter size={15} />
              적용
            </button>
            <button
              type="button"
              onClick={resetFilters}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]"
            >
              <RotateCcw size={15} />
              초기화
            </button>
          </div>
          {optionsTruncated && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              선택 목록은 최대 {optionLimit.toLocaleString()}개까지 표시됩니다. 더 많은 문제는 제목 또는 ID 검색을 사용하세요.
            </p>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 p-4 sm:p-6 lg:overflow-y-auto">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 pb-10">
          {errorMessage && (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">
              {errorMessage}
            </div>
          )}

          <div className="grid gap-4 xl:grid-cols-2">
            <GroupTable
              title="문제별 집계"
              icon={<Layers3 size={16} className="shrink-0 text-blue-500" />}
              groups={visibleProblemGroups}
              emptyText="표시할 문제가 없습니다."
              onPickProblem={selectProblem}
              onPickContest={selectContest}
            />
            <GroupTable
              title="유저별 집계"
              icon={<UserRound size={16} className="shrink-0 text-emerald-500" />}
              groups={visibleUserGroups}
              emptyText="표시할 유저가 없습니다."
              onPickUser={(username) => updateFilter('username', username)}
            />
          </div>

          <section className="overflow-hidden rounded-md border border-gray-200 bg-white dark:border-[#333] dark:bg-[#1a1a1a]">
            <div className="flex flex-col gap-3 border-b border-gray-200 px-4 py-3 dark:border-[#333] sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2">
                <Clock3 size={16} className="text-gray-500 dark:text-gray-400" />
                <h2 className="text-sm font-bold">작업 목록</h2>
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                <button
                  type="button"
                  onClick={() => updatePage(currentPage - 1)}
                  disabled={currentPage <= 1}
                  className="rounded border border-gray-200 p-1 disabled:cursor-not-allowed disabled:opacity-40 dark:border-[#444]"
                  title="이전 페이지"
                >
                  <ChevronLeft size={14} />
                </button>
                <span className="font-mono">
                  {currentPage} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => updatePage(currentPage + 1)}
                  disabled={currentPage >= totalPages}
                  className="rounded border border-gray-200 p-1 disabled:cursor-not-allowed disabled:opacity-40 dark:border-[#444]"
                  title="다음 페이지"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              {isLoading || (!hasCurrentResults && !errorMessage) ? (
                <div className="flex min-h-[260px] items-center justify-center gap-3 text-gray-500 dark:text-gray-400">
                  <RefreshCw size={18} className="animate-spin" />
                  불러오는 중...
                </div>
              ) : visibleJobs.length === 0 ? (
                <div className="flex min-h-[260px] items-center justify-center text-gray-500 dark:text-gray-400">
                  큐 작업이 없습니다.
                </div>
              ) : (
                <table className="w-full min-w-[1320px] table-fixed text-left text-sm">
                  <thead className="bg-gray-50 text-xs font-semibold text-gray-500 dark:bg-[#151515] dark:text-gray-400">
                    <tr>
                      <th className="w-[110px] px-4 py-3">상태</th>
                      <th className="w-[140px] px-3 py-3">판정</th>
                      <th className="w-[90px] px-3 py-3">작업</th>
                      <th className="w-[24%] px-3 py-3">문제</th>
                      <th className="w-[16%] px-3 py-3">기록 맥락</th>
                      <th className="w-[16%] px-3 py-3">사용자</th>
                      <th className="w-[90px] px-3 py-3 text-right">대기</th>
                      <th className="w-[90px] px-3 py-3 text-right">실행</th>
                      <th className="w-[90px] px-3 py-3 text-right">크기</th>
                      <th className="w-[110px] px-3 py-3">요청</th>
                      <th className="w-[80px] px-3 py-3 text-right">위치</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-[#282828]">
                    {visibleJobs.map((job) => {
                      const isAccepted = job.verdict === 'accepted' || job.verdict === 'compile_success' || job.verdict === 'finished';
                      const isTimed = job.verdict === 'time_limit_exceeded';
                      const isMemory = job.verdict === 'memory_limit_exceeded';
                      const isOutput = job.verdict === 'output_limit_exceeded';
                      const isCompileResource = job.verdict === 'compile_resource_error';
                      return (
                        <Fragment key={job.id}>
                          <tr className="hover:bg-gray-50 dark:hover:bg-[#202020]">
                            <td className="px-4 py-3">
                              <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-semibold ${statusClass[job.status]}`}>
                                {statusLabels[job.status]}
                              </span>
                            </td>
                            <td className="px-3 py-3">
                              <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-semibold ${verdictClass[job.verdict]}`}>
                                {isAccepted ? <CheckCircle2 size={12} /> : isTimed ? <Timer size={12} /> : isOutput ? <Layers3 size={12} /> : isMemory || isCompileResource ? <Cpu size={12} /> : <XCircle size={12} />}
                                {verdictLabels[job.verdict]}
                              </span>
                            </td>
                            <td className="px-3 py-3 text-gray-700 dark:text-gray-300">{kindLabels[job.kind]}</td>
                            <td className="min-w-0 px-3 py-3">
                              <button
                                type="button"
                                disabled={!job.problemId}
                                onClick={() => job.problemId && selectProblem(job.problemId, {
                                  contestId: job.contestId ?? null,
                                })}
                                className="block max-w-full truncate text-left font-medium text-gray-900 enabled:hover:text-blue-600 disabled:cursor-default dark:text-white dark:enabled:hover:text-blue-300"
                              >
                                {getProblemLabel(job)}
                              </button>
                              <p className="mt-0.5 truncate font-mono text-xs text-gray-500 dark:text-gray-500">
                                {job.problemId || 'main'} · {job.language}
                              </p>
                            </td>
                            <td className="min-w-0 px-3 py-3">
                              <div className="flex flex-wrap gap-1">
                                {sourceLabel(job.source) && (
                                  <button
                                    type="button"
                                    onClick={() => job.source && updateSource(job.source)}
                                    className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.5 text-xs font-medium text-sky-700 hover:bg-sky-500/20 dark:text-sky-200"
                                    aria-label={`${sourceLabel(job.source)} 기록으로 필터`}
                                  >
                                    {sourceLabel(job.source)}
                                  </button>
                                )}
                                {job.contestId && (
                                  <button
                                    type="button"
                                    onClick={() => selectContest(job.contestId!)}
                                    className="max-w-full truncate rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-0.5 text-left text-xs font-medium text-violet-700 hover:bg-violet-500/20 dark:text-violet-200"
                                    aria-label={`${job.contestTitle || job.contestId} 대회로 필터`}
                                  >
                                    {job.contestTitle || job.contestId}
                                  </button>
                                )}
                                {!sourceLabel(job.source) && !job.contestId && <span className="text-xs text-gray-400">-</span>}
                              </div>
                            </td>
                            <td className="px-3 py-3">
                              <button
                                type="button"
                                disabled={!job.username}
                                onClick={() => job.username && updateFilter('username', job.username)}
                                className="block max-w-full truncate text-left text-gray-700 enabled:hover:text-blue-600 disabled:cursor-default dark:text-gray-300 dark:enabled:hover:text-blue-300"
                              >
                                {getUsernameLabel(job)}
                              </button>
                            </td>
                            <td className="px-3 py-3 text-right font-mono text-xs text-gray-600 dark:text-gray-400">{formatDuration(job.waitMs)}</td>
                            <td className="px-3 py-3 text-right font-mono text-xs text-gray-600 dark:text-gray-400">{formatDuration(job.runMs)}</td>
                            <td className="px-3 py-3 text-right font-mono text-xs text-gray-600 dark:text-gray-400">{formatBytes(job.sourceSizeBytes)}</td>
                            <td className="px-3 py-3 font-mono text-xs text-gray-600 dark:text-gray-400">{formatDate(job.queuedAt)}</td>
                            <td className="px-3 py-3 text-right font-mono text-xs text-gray-600 dark:text-gray-400">
                              {job.position ? `#${job.position}` : '-'}
                            </td>
                          </tr>
                          {(job.error || job.verdictDetail) && (
                            <tr className="bg-red-500/5">
                              <td colSpan={11} className="px-4 pb-3 text-xs text-red-600 dark:text-red-300">
                                {job.error || job.verdictDetail}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
