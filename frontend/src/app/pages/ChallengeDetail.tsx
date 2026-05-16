import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { ArrowLeft, PlayCircle, Tag, Loader2, AlertCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { getProblems } from '../services/problemApi';
import type { Problem, ProblemTag } from '../services/problemApi';
import { DIFFICULTY_LABELS, getDifficultyBadgeClass } from '../constants/difficulty';

type Difficulty = Problem['difficulty'];
type ChallengeTag = ProblemTag;

const tagLabels: Record<ChallengeTag, string> = {
  io: '입출력',
  control: '제어문',
  func: '함수'
};

const tagColors = {
  io: 'text-blue-300 bg-blue-500/10 border-blue-500/20',
  control: 'text-purple-300 bg-purple-500/10 border-purple-500/20',
  func: 'text-pink-300 bg-pink-500/10 border-pink-500/20'
};

export function ChallengeDetail() {
  const navigate = useNavigate();
  const { challengeId } = useParams<{ challengeId: string }>();
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    getProblems()
      .then((data) => {
        setProblems(data);
        setLoadError(null);
      })
      .catch(() => {
        setLoadError('문제를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
      })
      .finally(() => setLoading(false));
  }, []);

  const challenge = useMemo(
    () => problems.find((problem) => String(problem.id) === String(challengeId)),
    [problems, challengeId]
  );

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

          <button
            onClick={() => navigate('/', { state: { challenge } })}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg bg-blue-600 hover:bg-blue-700 text-white"
          >
            <PlayCircle size={16} />
            문제 풀기
          </button>
        </div>

        <section className="rounded-xl border border-gray-300 dark:border-[#333] bg-gray-50 dark:bg-[#161616] p-6 md:p-8">
          <div className="flex flex-wrap items-center gap-2 mb-3">
            <span className={`px-2.5 py-1 rounded-md text-xs font-semibold border uppercase tracking-wider ${getDifficultyBadgeClass(challenge.difficulty)}`}>
              {DIFFICULTY_LABELS[challenge.difficulty as Difficulty] ?? challenge.difficulty}
            </span>
            {(challenge.tags ?? []).map((tag) => (
              <span key={tag} className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border ${tagColors[tag]}`}>
                <Tag size={12} />
                {tagLabels[tag]}
              </span>
            ))}
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
                    예시 {index + 1}
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
              등록된 테스트케이스가 없습니다.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
