import { useCallback, useEffect, useMemo, useState } from 'react';
import { CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, Filter, RefreshCw, RotateCcw, XCircle } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router';
import { getSubmissions, type SubmissionFilters, type SubmissionRecord } from '../services/problemApi';
import type { CompileQueueVerdict } from '../services/compilerApi';

const PAGE_SIZE = 50;

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
  system_error: '시스템 오류',
  canceled: '취소',
};

const statusLabels: Record<string, string> = {
  Accepted: '정답',
  Rejected: '실패',
  SampleFailed: '예제 실패',
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
  system_error: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  canceled: 'border-gray-500/30 bg-gray-500/10 text-gray-700 dark:text-gray-300',
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return date.toLocaleString('ko-KR');
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
    { value: 'system_error', label: '시스템 오류' },
  ];
}

function statusOptions() {
  return [
    { value: '', label: '전체 상태' },
    { value: 'Accepted', label: '정답' },
    { value: 'Rejected', label: '실패' },
    { value: 'SampleFailed', label: '예제 실패' },
  ];
}

export function Submissions() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [submissions, setSubmissions] = useState<SubmissionRecord[]>([]);
  const [filteredTotal, setFilteredTotal] = useState(0);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [problemInput, setProblemInput] = useState(searchParams.get('problemId') || '');
  const [usernameInput, setUsernameInput] = useState(searchParams.get('username') || '');

  const currentPage = Math.max(1, Number(searchParams.get('page') || '1') || 1);
  const verdictFilter = (searchParams.get('verdict') || 'all') as CompileQueueVerdict | 'all';
  const statusFilter = searchParams.get('status') || '';
  const mineFilter = searchParams.get('mine') === 'true';

  useEffect(() => {
    setProblemInput(searchParams.get('problemId') || '');
    setUsernameInput(searchParams.get('username') || '');
  }, [searchParams]);

  const filters = useMemo<SubmissionFilters>(
    () => ({
      limit: PAGE_SIZE,
      offset: (currentPage - 1) * PAGE_SIZE,
      problemId: searchParams.get('problemId') || undefined,
      username: searchParams.get('username') || undefined,
      verdict: verdictFilter,
      status: statusFilter || undefined,
      mine: mineFilter,
    }),
    [currentPage, mineFilter, searchParams, statusFilter, verdictFilter],
  );

  const loadSubmissions = useCallback(async () => {
    try {
      setErrorMessage(null);
      const response = await getSubmissions(filters);
      setSubmissions(response.submissions);
      setFilteredTotal(response.filteredTotal);
      setTotal(response.total);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '제출 이력을 불러오지 못했습니다.');
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    setIsLoading(true);
    void loadSubmissions();
  }, [loadSubmissions]);

  const totalPages = Math.max(1, Math.ceil(filteredTotal / PAGE_SIZE));

  const updateFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (!value || value === 'all') next.delete(key);
    else next.set(key, value);
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
    if (problemInput.trim()) next.set('problemId', problemInput.trim());
    else next.delete('problemId');
    if (usernameInput.trim()) next.set('username', usernameInput.trim());
    else next.delete('username');
    next.delete('page');
    setSearchParams(next);
  };

  const resetFilters = () => {
    setProblemInput('');
    setUsernameInput('');
    setSearchParams({});
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-50 text-gray-900 dark:bg-[#121212] dark:text-white">
      <div className="shrink-0 border-b border-gray-200 bg-white px-6 py-5 dark:border-[#333] dark:bg-[#1e1e1e]">
        <div className="mx-auto flex max-w-7xl flex-col gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="mb-2 flex items-center gap-3">
                <ClipboardList className="text-blue-600 dark:text-blue-400" size={28} />
                <h1 className="text-2xl font-bold">제출 이력</h1>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-gray-600 dark:text-gray-400">
                <span>표시 {filteredTotal.toLocaleString()}</span>
                <span>전체 {total.toLocaleString()}</span>
              </div>
            </div>
            <button
              onClick={() => void loadSubmissions()}
              disabled={isLoading}
              className="inline-flex w-fit items-center gap-2 rounded-md border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]"
            >
              <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
              새로고침
            </button>
          </div>

          <div className="grid gap-3 xl:grid-cols-[170px_170px_minmax(170px,1fr)_minmax(170px,1fr)_auto_auto_auto]">
            <select
              value={statusFilter}
              onChange={(event) => updateFilter('status', event.target.value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white"
            >
              {statusOptions().map((option) => (
                <option key={option.value || 'all'} value={option.value}>{option.label}</option>
              ))}
            </select>
            <select
              value={verdictFilter}
              onChange={(event) => updateFilter('verdict', event.target.value)}
              className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 dark:border-[#333] dark:bg-[#141414] dark:text-white"
            >
              {verdictOptions().map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <input
              value={problemInput}
              onChange={(event) => setProblemInput(event.target.value)}
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
              onClick={() => updateFilter('mine', mineFilter ? '' : 'true')}
              className={`inline-flex items-center justify-center rounded-md border px-4 py-2 text-sm font-semibold transition-colors ${
                mineFilter
                  ? 'border-blue-500 bg-blue-500 text-white'
                  : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-100 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]'
              }`}
            >
              내 제출
            </button>
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
        <div className="mx-auto max-w-7xl pb-10">
          {errorMessage && (
            <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-300">
              {errorMessage}
            </div>
          )}

          <section className="overflow-hidden rounded-md border border-gray-200 bg-white dark:border-[#333] dark:bg-[#1a1a1a]">
            <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-[#333]">
              <h2 className="text-sm font-bold">제출 목록</h2>
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
                <span className="font-mono">{currentPage} / {totalPages}</span>
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
              {isLoading && submissions.length === 0 ? (
                <div className="flex min-h-[260px] items-center justify-center gap-3 text-gray-500 dark:text-gray-400">
                  <RefreshCw size={18} className="animate-spin" />
                  불러오는 중...
                </div>
              ) : submissions.length === 0 ? (
                <div className="flex min-h-[260px] items-center justify-center text-gray-500 dark:text-gray-400">
                  제출 이력이 없습니다.
                </div>
              ) : (
                <table className="w-full min-w-[980px] table-fixed text-left text-sm">
                  <thead className="bg-gray-50 text-xs font-semibold text-gray-500 dark:bg-[#151515] dark:text-gray-400">
                    <tr>
                      <th className="w-[150px] px-4 py-3">판정</th>
                      <th className="w-[110px] px-3 py-3">상태</th>
                      <th className="w-[28%] px-3 py-3">문제</th>
                      <th className="w-[16%] px-3 py-3">사용자</th>
                      <th className="w-[110px] px-3 py-3">예제 채점</th>
                      <th className="w-[90px] px-3 py-3 text-right">점수</th>
                      <th className="w-[160px] px-3 py-3">제출 시간</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200 dark:divide-[#282828]">
                    {submissions.map((submission) => {
                      const accepted = submission.verdict === 'accepted';
                      return (
                        <tr key={submission.id} className="hover:bg-gray-50 dark:hover:bg-[#202020]">
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-semibold ${verdictClass[submission.verdict]}`}>
                              {accepted ? <CheckCircle2 size={12} /> : <XCircle size={12} />}
                              {verdictLabels[submission.verdict]}
                            </span>
                          </td>
                          <td className="px-3 py-3 text-gray-700 dark:text-gray-300">
                            {statusLabels[submission.status] ?? submission.status}
                          </td>
                          <td className="min-w-0 px-3 py-3">
                            <button
                              type="button"
                              onClick={() => navigate(`/challenges/${submission.problemId}`)}
                              className="block max-w-full truncate text-left font-medium text-gray-900 hover:text-blue-600 dark:text-white dark:hover:text-blue-300"
                            >
                              {submission.problemTitle ?? submission.problemId}
                            </button>
                            <p className="mt-0.5 truncate font-mono text-xs text-gray-500">{submission.problemId}</p>
                          </td>
                          <td className="px-3 py-3 text-gray-700 dark:text-gray-300">{submission.username ?? '익명'}</td>
                          <td className="px-3 py-3 font-mono text-xs text-gray-600 dark:text-gray-400">
                            {submission.samplePassedCases}/{submission.sampleTotalCases}
                          </td>
                          <td className="px-3 py-3 text-right font-mono text-xs text-gray-600 dark:text-gray-400">
                            {submission.awardedPoints}
                          </td>
                          <td className="px-3 py-3 text-xs text-gray-600 dark:text-gray-400">
                            {formatDate(submission.createdAt)}
                          </td>
                        </tr>
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
