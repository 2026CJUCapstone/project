import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, Clock3, Filter, Layers3, RefreshCw, RotateCcw, UserRound } from 'lucide-react';
import { useSearchParams } from 'react-router';
import {
  getCompileQueue,
  type CompileQueueFilters,
  type CompileQueueJob,
  type CompileQueueKind,
  type CompileQueueStatus,
} from '../services/compilerApi';

const statusLabels: Record<CompileQueueStatus, string> = {
  queued: '대기',
  running: '실행 중',
  completed: '완료',
  failed: '실패',
  canceled: '취소',
};

const kindLabels: Record<CompileQueueKind, string> = {
  compile: '컴파일',
  run: '실행',
  grading: '채점',
};

const statusClass: Record<CompileQueueStatus, string> = {
  queued: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  running: 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300',
  completed: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  failed: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  canceled: 'border-gray-500/30 bg-gray-500/10 text-gray-700 dark:text-gray-300',
};

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

function statusOptions() {
  return [
    { value: 'all', label: '전체 상태' },
    { value: 'queued', label: '대기' },
    { value: 'running', label: '실행 중' },
    { value: 'completed', label: '완료' },
    { value: 'failed', label: '실패' },
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

function getProblemLabel(job: CompileQueueJob): string {
  return job.problemTitle || job.problemId || '일반 컴파일';
}

function getUsernameLabel(job: CompileQueueJob): string {
  return job.username || '익명';
}

export function CompileQueue() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [jobs, setJobs] = useState<CompileQueueJob[]>([]);
  const [queued, setQueued] = useState(0);
  const [running, setRunning] = useState(0);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [usernameInput, setUsernameInput] = useState(searchParams.get('username') || '');
  const [problemIdInput, setProblemIdInput] = useState(searchParams.get('problemId') || '');
  const statusFilter = (searchParams.get('status') || 'all') as CompileQueueStatus | 'all';
  const kindFilter = (searchParams.get('kind') || 'all') as CompileQueueKind | 'all';

  useEffect(() => {
    setUsernameInput(searchParams.get('username') || '');
    setProblemIdInput(searchParams.get('problemId') || '');
  }, [searchParams]);

  const filters = useMemo<CompileQueueFilters>(
    () => ({
      limit: 150,
      status: statusFilter,
      kind: kindFilter,
      username: searchParams.get('username') || undefined,
      problemId: searchParams.get('problemId') || undefined,
    }),
    [kindFilter, searchParams, statusFilter],
  );

  const loadQueue = useCallback(async () => {
    try {
      setErrorMessage(null);
      const response = await getCompileQueue(filters);
      setJobs(response.jobs);
      setQueued(response.queued);
      setRunning(response.running);
      setTotal(response.total);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '컴파일 큐를 불러오지 못했습니다.');
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    setIsLoading(true);
    void loadQueue();
    const interval = window.setInterval(() => {
      void loadQueue();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [loadQueue]);

  const groupedByProblem = useMemo(() => {
    const counts = new Map<string, { label: string; problemId: string; count: number; running: number; queued: number }>();
    for (const job of jobs) {
      const key = job.problemId || '__main__';
      const current = counts.get(key) || {
        label: getProblemLabel(job),
        problemId: job.problemId || '',
        count: 0,
        running: 0,
        queued: 0,
      };
      current.count += 1;
      if (job.status === 'running') current.running += 1;
      if (job.status === 'queued') current.queued += 1;
      counts.set(key, current);
    }
    return [...counts.values()].sort((a, b) => b.count - a.count).slice(0, 8);
  }, [jobs]);

  const groupedByUser = useMemo(() => {
    const counts = new Map<string, { username: string; count: number; running: number; queued: number }>();
    for (const job of jobs) {
      const username = getUsernameLabel(job);
      const current = counts.get(username) || { username, count: 0, running: 0, queued: 0 };
      current.count += 1;
      if (job.status === 'running') current.running += 1;
      if (job.status === 'queued') current.queued += 1;
      counts.set(username, current);
    }
    return [...counts.values()].sort((a, b) => b.count - a.count).slice(0, 8);
  }, [jobs]);

  const updateFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (!value || value === 'all') {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setSearchParams(next);
  };

  const applyTextFilters = () => {
    const next = new URLSearchParams(searchParams);
    const username = usernameInput.trim();
    const problemId = problemIdInput.trim();
    if (username) next.set('username', username);
    else next.delete('username');
    if (problemId) next.set('problemId', problemId);
    else next.delete('problemId');
    setSearchParams(next);
  };

  const resetFilters = () => {
    setUsernameInput('');
    setProblemIdInput('');
    setSearchParams({});
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-50 text-gray-900 transition-colors duration-200 dark:bg-[#121212] dark:text-white">
      <div className="shrink-0 border-b border-gray-200 bg-white px-6 py-6 transition-colors duration-200 dark:border-[#333] dark:bg-[#1e1e1e]">
        <div className="mx-auto flex max-w-7xl flex-col gap-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="mb-2 flex items-center gap-3">
                <Activity className="text-blue-600 dark:text-blue-400" size={30} />
                <h1 className="text-2xl font-bold">컴파일 큐</h1>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400">
                현재 대기 중인 컴파일, 실행, 채점 작업과 최근 처리 기록입니다.
              </p>
            </div>

            <button
              onClick={() => void loadQueue()}
              disabled={isLoading}
              className="inline-flex w-fit items-center gap-2 rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]"
            >
              <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
              새로고침
            </button>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 dark:border-[#333] dark:bg-[#151515]">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">대기</p>
              <p className="mt-1 text-xl font-bold text-amber-600 dark:text-amber-300">{queued.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 dark:border-[#333] dark:bg-[#151515]">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">실행 중</p>
              <p className="mt-1 text-xl font-bold text-blue-600 dark:text-blue-300">{running.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 dark:border-[#333] dark:bg-[#151515]">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">보관된 작업</p>
              <p className="mt-1 text-xl font-bold">{total.toLocaleString()}</p>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-[160px_160px_minmax(180px,1fr)_minmax(180px,1fr)_auto_auto]">
            <select
              value={statusFilter}
              onChange={(event) => updateFilter('status', event.target.value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white"
            >
              {statusOptions().map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={kindFilter}
              onChange={(event) => updateFilter('kind', event.target.value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white"
            >
              {kindOptions().map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <input
              value={problemIdInput}
              onChange={(event) => setProblemIdInput(event.target.value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white"
              placeholder="문제 ID"
            />
            <input
              value={usernameInput}
              onChange={(event) => setUsernameInput(event.target.value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white"
              placeholder="사용자 이름"
            />
            <button
              onClick={applyTextFilters}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700"
            >
              <Filter size={15} />
              적용
            </button>
            <button
              onClick={resetFilters}
              className="inline-flex items-center justify-center gap-2 rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]"
            >
              <RotateCcw size={15} />
              초기화
            </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 pb-10">
          {errorMessage && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">
              {errorMessage}
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="rounded-lg border border-gray-200 bg-white dark:border-[#333] dark:bg-[#1a1a1a]">
              <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3 dark:border-[#333]">
                <Layers3 size={16} className="text-blue-500" />
                <h2 className="text-sm font-bold">문제별</h2>
              </div>
              <div className="divide-y divide-gray-200 dark:divide-[#282828]">
                {groupedByProblem.length === 0 ? (
                  <div className="px-4 py-6 text-sm text-gray-500 dark:text-gray-400">표시할 작업이 없습니다.</div>
                ) : (
                  groupedByProblem.map((item) => (
                    <button
                      key={item.problemId || item.label}
                      onClick={() => item.problemId && updateFilter('problemId', item.problemId)}
                      className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50 dark:hover:bg-[#202020]"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-gray-900 dark:text-white">{item.label}</p>
                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          대기 {item.queued} · 실행 {item.running}
                        </p>
                      </div>
                      <span className="font-mono text-sm text-gray-600 dark:text-gray-300">{item.count}</span>
                    </button>
                  ))
                )}
              </div>
            </section>

            <section className="rounded-lg border border-gray-200 bg-white dark:border-[#333] dark:bg-[#1a1a1a]">
              <div className="flex items-center gap-2 border-b border-gray-200 px-4 py-3 dark:border-[#333]">
                <UserRound size={16} className="text-emerald-500" />
                <h2 className="text-sm font-bold">유저별</h2>
              </div>
              <div className="divide-y divide-gray-200 dark:divide-[#282828]">
                {groupedByUser.length === 0 ? (
                  <div className="px-4 py-6 text-sm text-gray-500 dark:text-gray-400">표시할 작업이 없습니다.</div>
                ) : (
                  groupedByUser.map((item) => (
                    <button
                      key={item.username}
                      onClick={() => item.username !== '익명' && updateFilter('username', item.username)}
                      className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50 dark:hover:bg-[#202020]"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-gray-900 dark:text-white">{item.username}</p>
                        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                          대기 {item.queued} · 실행 {item.running}
                        </p>
                      </div>
                      <span className="font-mono text-sm text-gray-600 dark:text-gray-300">{item.count}</span>
                    </button>
                  ))
                )}
              </div>
            </section>
          </div>

          <section className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-[#333] dark:bg-[#1a1a1a]">
            <div className="grid grid-cols-[96px_96px_minmax(160px,1fr)_minmax(130px,0.7fr)_100px_100px_100px_90px] gap-3 border-b border-gray-200 px-4 py-3 text-xs font-semibold text-gray-500 dark:border-[#333] dark:text-gray-400">
              <div>상태</div>
              <div>작업</div>
              <div>문제</div>
              <div>사용자</div>
              <div>대기</div>
              <div>실행</div>
              <div>요청</div>
              <div className="text-right">위치</div>
            </div>

            {isLoading && jobs.length === 0 ? (
              <div className="flex min-h-[260px] items-center justify-center gap-3 text-gray-500 dark:text-gray-400">
                <RefreshCw size={18} className="animate-spin" />
                불러오는 중...
              </div>
            ) : jobs.length === 0 ? (
              <div className="flex min-h-[260px] items-center justify-center text-gray-500 dark:text-gray-400">
                큐 작업이 없습니다.
              </div>
            ) : (
              <div className="divide-y divide-gray-200 dark:divide-[#282828]">
                {jobs.map((job) => (
                  <div
                    key={job.id}
                    className="grid grid-cols-[96px_96px_minmax(160px,1fr)_minmax(130px,0.7fr)_100px_100px_100px_90px] gap-3 px-4 py-3 text-sm transition-colors hover:bg-gray-50 dark:hover:bg-[#202020]"
                  >
                    <div>
                      <span className={`inline-flex rounded border px-2 py-0.5 text-xs font-semibold ${statusClass[job.status]}`}>
                        {statusLabels[job.status]}
                      </span>
                    </div>
                    <div className="text-gray-700 dark:text-gray-300">{kindLabels[job.kind]}</div>
                    <div className="min-w-0">
                      <p className="truncate font-medium text-gray-900 dark:text-white">{getProblemLabel(job)}</p>
                      <p className="mt-0.5 truncate font-mono text-xs text-gray-500 dark:text-gray-500">
                        {job.problemId || 'main'} · {job.language}
                      </p>
                    </div>
                    <div className="truncate text-gray-700 dark:text-gray-300">{getUsernameLabel(job)}</div>
                    <div className="font-mono text-xs text-gray-600 dark:text-gray-400">{formatDuration(job.waitMs)}</div>
                    <div className="font-mono text-xs text-gray-600 dark:text-gray-400">{formatDuration(job.runMs)}</div>
                    <div className="inline-flex items-center gap-1 text-xs text-gray-600 dark:text-gray-400">
                      <Clock3 size={12} />
                      {formatDate(job.queuedAt)}
                    </div>
                    <div className="text-right font-mono text-xs text-gray-600 dark:text-gray-400">
                      {job.position ? `#${job.position}` : '-'}
                    </div>
                    {job.error && (
                      <div className="col-span-8 truncate text-xs text-red-600 dark:text-red-300">{job.error}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
