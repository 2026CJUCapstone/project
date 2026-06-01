import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { ArrowLeft, PlayCircle, Tag, Loader2, AlertCircle, Activity, CheckCircle2, Clock3 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { getProblem, getSubmissions } from '../services/problemApi';
import type { Problem, SubmissionRecord } from '../services/problemApi';
import { DIFFICULTY_LABELS, getDifficultyBadgeClass } from '../constants/difficulty';
import { getProblemTagClass, getProblemTagLabel } from '../constants/problemTags';

type Difficulty = Problem['difficulty'];

const verdictLabels: Record<string, string> = {
  accepted: '정답',
  wrong_answer: '오답',
  compile_error: '컴파일 실패',
  runtime_error: '런타임 오류',
  time_limit_exceeded: '시간 초과',
  memory_limit_exceeded: '메모리 초과',
  system_error: '시스템 오류',
  pending: '대기',
  running: '실행 중',
  compile_success: '컴파일 성공',
  finished: '정상 종료',
  canceled: '취소',
};

function formatSubmissionTime(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return date.toLocaleString('ko-KR');
}

export function ChallengeDetail() {
  const navigate = useNavigate();
  const { challengeId } = useParams<{ challengeId: string }>();
  const [challenge, setChallenge] = useState<Problem | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submissions, setSubmissions] = useState<SubmissionRecord[]>([]);

  useEffect(() => {
    if (!challengeId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    getProblem(challengeId)
      .then((data) => {
        setChallenge(data);
        setLoadError(null);
      })
      .catch(() => {
        setLoadError('문제를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
      })
      .finally(() => setLoading(false));
  }, [challengeId]);

  useEffect(() => {
    if (!challengeId) return;
    let mounted = true;
    getSubmissions({ problemId: challengeId, limit: 5 })
      .then((response) => {
        if (mounted) setSubmissions(response.submissions);
      })
      .catch(() => {
        if (mounted) setSubmissions([]);
      });
    return () => {
      mounted = false;
    };
  }, [challengeId]);

  if (loading) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-white dark:bg-[#121212]">
        <div className="flex flex-col items-center gap-3 text-gray-500">
          <Loader2 size={30} className="animate-spin" />
          <p className="text-sm">문제 상세를 불러오는 중...</p>
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-white dark:bg-[#121212] p-6">
        <div className="max-w-md w-full rounded-xl border border-red-300/40 bg-red-50/60 dark:bg-red-900/10 dark:border-red-500/30 p-6">
          <div className="flex items-start gap-3">
            <AlertCircle className="text-red-500 shrink-0 mt-0.5" size={20} />
            <div>
              <h2 className="text-lg font-bold text-red-600 dark:text-red-400 mb-1">문제 로딩 실패</h2>
              <p className="text-sm text-gray-700 dark:text-gray-300">{loadError}</p>
              <button
                onClick={() => navigate('/challenges')}
                className="mt-4 px-3 py-2 text-sm rounded-md border border-gray-300 dark:border-[#444] bg-white dark:bg-[#1e1e1e] hover:bg-gray-50 dark:hover:bg-[#252525]"
              >
                목록으로 돌아가기
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!challenge) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-white dark:bg-[#121212] p-6">
        <div className="max-w-md w-full rounded-xl border border-gray-300 dark:border-[#444] bg-gray-50 dark:bg-[#1a1a1a] p-6 text-center">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-2">문제를 찾을 수 없습니다</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">삭제되었거나 잘못된 URL일 수 있습니다.</p>
          <button
            onClick={() => navigate('/challenges')}
            className="px-3 py-2 text-sm rounded-md border border-gray-300 dark:border-[#444] bg-white dark:bg-[#1e1e1e] hover:bg-gray-100 dark:hover:bg-[#252525]"
          >
            목록으로 돌아가기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full overflow-y-auto bg-white dark:bg-[#121212] p-6 md:p-8">
      <div className="max-w-5xl mx-auto">
        <div className="flex items-center justify-between gap-3 mb-6">
          <button
            onClick={() => navigate('/challenges')}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-[#444] bg-white dark:bg-[#1e1e1e] text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-[#252525]"
          >
            <ArrowLeft size={16} />
            문제 목록
          </button>

          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(`/queue?problemId=${encodeURIComponent(challenge.id)}`)}
              className="inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-gray-300 dark:border-[#444] bg-white dark:bg-[#1e1e1e] text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-[#252525]"
            >
              <Activity size={16} />
              큐
            </button>
            <button
              onClick={() => navigate('/', { state: { challenge } })}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white"
            >
              <PlayCircle size={16} />
              문제 풀기
            </button>
          </div>
        </div>

        <section className="rounded-xl border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#161616] p-6 md:p-8">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <span className={`px-2.5 py-1 rounded-md text-xs font-semibold border uppercase tracking-wider ${getDifficultyBadgeClass(challenge.difficulty)}`}>
              {DIFFICULTY_LABELS[challenge.difficulty as Difficulty] ?? challenge.difficulty}
            </span>
            <span className="px-2.5 py-1 rounded-md text-xs font-semibold border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
              {challenge.points ?? 100}점
            </span>
	            {(challenge.tags ?? []).map((tag) => (
	              <span key={tag} className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border ${getProblemTagClass(tag)}`}>
	                <Tag size={12} />
	                {getProblemTagLabel(tag)}
	              </span>
	            ))}
	            <span className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border ${
	              challenge.solved
	                ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
	                : challenge.attempted
	                  ? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
	                  : 'border-gray-300 dark:border-[#333] text-gray-500 dark:text-gray-400'
	            }`}>
	              {challenge.solved ? <CheckCircle2 size={12} /> : <Clock3 size={12} />}
	              {challenge.solved ? '해결' : challenge.attempted ? '시도함' : '미시도'}
	            </span>
	          </div>

          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-8">{challenge.title}</h1>

          <div className="prose prose-sm md:prose-base dark:prose-invert max-w-none text-gray-800 dark:text-gray-200">
            <ReactMarkdown>{challenge.description}</ReactMarkdown>
          </div>

          {(challenge.testCases?.length ?? 0) > 0 ? (
            <div className="mt-8 space-y-4">
              {challenge.testCases.map((testCase, index) => (
                <div key={index} className="rounded-lg border border-gray-200 dark:border-[#333] p-4 bg-white/60 dark:bg-[#111]">
                  <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wider mb-3">
                    예제 {index + 1}
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <h4 className="text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-2">입력</h4>
                      <pre className="bg-white dark:bg-[#0d0d0d] border border-gray-200 dark:border-[#333] rounded-lg p-3 font-mono text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-words shadow-inner">{testCase.input || '(없음)'}</pre>
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-2">출력</h4>
                      <pre className="bg-white dark:bg-[#0d0d0d] border border-gray-200 dark:border-[#333] rounded-lg p-3 font-mono text-sm text-emerald-700 dark:text-emerald-400 whitespace-pre-wrap break-words shadow-inner">{testCase.expectedOutput || '(없음)'}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
	          ) : (
	            <div className="mt-8 rounded-lg border border-gray-200 dark:border-[#333] p-4 text-sm text-gray-600 dark:text-gray-400">
	              등록된 예제가 없습니다.
	            </div>
	          )}

	          <div className="mt-8 rounded-lg border border-gray-200 dark:border-[#333] bg-white/60 dark:bg-[#111]">
	            <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-[#333]">
	              <h2 className="text-sm font-bold text-gray-900 dark:text-white">최근 제출</h2>
	              <button
	                type="button"
	                onClick={() => navigate(`/submissions?problemId=${encodeURIComponent(challenge.id)}`)}
	                className="text-xs font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200"
	              >
	                전체 보기
	              </button>
	            </div>
	            {submissions.length === 0 ? (
	              <div className="px-4 py-5 text-sm text-gray-500 dark:text-gray-400">아직 제출 이력이 없습니다.</div>
	            ) : (
	              <div className="overflow-x-auto">
	                <table className="w-full min-w-[620px] text-left text-sm">
	                  <thead className="text-xs text-gray-500 dark:text-gray-400">
	                    <tr>
	                      <th className="px-4 py-2">판정</th>
	                      <th className="px-3 py-2">사용자</th>
	                      <th className="px-3 py-2">예제 채점</th>
	                      <th className="px-3 py-2">제출 시간</th>
	                    </tr>
	                  </thead>
	                  <tbody className="divide-y divide-gray-200 dark:divide-[#242424]">
	                    {submissions.map((submission) => (
	                      <tr key={submission.id}>
	                        <td className="px-4 py-2 font-semibold">
	                          <span className={submission.verdict === 'accepted' ? 'text-emerald-600 dark:text-emerald-300' : 'text-red-600 dark:text-red-300'}>
	                            {verdictLabels[submission.verdict] ?? submission.status}
	                          </span>
	                        </td>
	                        <td className="px-3 py-2 text-gray-600 dark:text-gray-300">{submission.username ?? '익명'}</td>
	                        <td className="px-3 py-2 font-mono text-xs text-gray-600 dark:text-gray-400">
	                          {submission.samplePassedCases}/{submission.sampleTotalCases}
	                        </td>
	                        <td className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
	                          {formatSubmissionTime(submission.createdAt)}
	                        </td>
	                      </tr>
	                    ))}
	                  </tbody>
	                </table>
	              </div>
	            )}
	          </div>
	        </section>
      </div>
    </div>
  );
}
