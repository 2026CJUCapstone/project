import { useState } from "react";
import { CheckCircle, XCircle, Clock, Send } from "lucide-react";
import { submitProblem, type ProblemSubmissionResult, type TestCase } from "../services/problemApi";

interface Props {
  code: string;
  challengeId: string;
  challengeTitle: string;
  testCases: TestCase[];
  onClose: () => void;
}

export function JudgePanel({ code, challengeId, challengeTitle, testCases, onClose }: Props) {
  const [result, setResult] = useState<ProblemSubmissionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isJudging, setIsJudging] = useState(false);

  const sampleProgress = result
    ? Math.round((result.samplePassedCases / Math.max(result.sampleTotalCases, 1)) * 100)
    : 0;
  const gradingStatus = result?.gradingCompleted
    ? result.gradingPassed ? '통과' : '실패'
    : '미진행';

  const handleSubmit = async () => {
    setIsJudging(true);
    setError(null);
    try {
      const res = await submitProblem(challengeId, code, 'bpp');
      setResult(res);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '제출에 실패했습니다.');
      setResult(null);
    } finally {
      setIsJudging(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d] text-gray-100">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#1e1e1e] border-b border-[#333] shrink-0">
        <div className="flex items-center gap-2">
          <Send size={14} className="text-green-400" />
          <span className="text-xs font-semibold uppercase tracking-widest text-gray-200">
            채점 - {challengeTitle}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSubmit}
            disabled={isJudging}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white text-xs font-semibold rounded transition-colors"
          >
            {isJudging ? "채점 중..." : "제출"}
          </button>
          <button
            onClick={onClose}
            className="text-xs text-gray-400 hover:text-gray-200 transition-colors"
          >
            닫기
          </button>
        </div>
      </div>

      {/* 결과 */}
      <div className="flex-1 overflow-y-auto p-4">
        {!result && !isJudging && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500 text-sm">
            <Send size={32} className="mb-3 text-gray-600" />
            <p>예제 채점을 먼저 확인한 뒤 채점을 진행합니다</p>
            <p className="text-xs mt-1 text-gray-600">공개 예시 {testCases.length}개</p>
          </div>
        )}

        {error && !isJudging && (
          <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {isJudging && (
          <div className="flex items-center justify-center h-full text-gray-400 text-sm">
            <Clock size={16} className="animate-spin mr-2" />
            채점 중...
          </div>
        )}

        {result && (
          <div className="flex flex-col gap-3">
            {/* 요약 */}
            <div className={`flex items-center gap-3 p-3 rounded-lg border ${
              result.status === 'Accepted'
                ? "bg-green-500/10 border-green-500/30"
                : "bg-red-500/10 border-red-500/30"
            }`}>
              {result.status === 'Accepted' ? (
                <CheckCircle size={20} className="text-green-400" />
              ) : (
                <XCircle size={20} className="text-red-400" />
              )}
              <div>
                <p className={`text-sm font-bold ${result.status === 'Accepted' ? "text-green-400" : "text-red-400"}`}>
                  {result.status === 'Accepted' ? '정답입니다!' : '채점 완료'}
                </p>
                <p className="text-xs text-gray-400">
                  예제 채점 {result.samplePassedCases}/{result.sampleTotalCases} 통과 · 채점 {gradingStatus}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="rounded-lg border border-[#333] bg-[#111] p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">예제 채점</p>
                <p className="text-2xl font-bold text-blue-300 mb-2">{sampleProgress}%</p>
                <div className="h-2 rounded-full bg-[#1f1f1f] overflow-hidden mb-2">
                  <div className="h-full bg-blue-500" style={{ width: `${sampleProgress}%` }} />
                </div>
                <p className="text-[11px] text-gray-500">{result.samplePassedCases}/{result.sampleTotalCases} 통과</p>
              </div>
              <div className="rounded-lg border border-[#333] bg-[#111] p-3">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-500 mb-2">채점</p>
                <p className={`text-2xl font-bold mb-2 ${result.gradingPassed ? 'text-green-300' : 'text-amber-300'}`}>
                  {gradingStatus}
                </p>
                <div className="h-2 rounded-full bg-[#1f1f1f] overflow-hidden mb-2">
                  <div
                    className={`h-full ${result.gradingPassed ? 'bg-green-500' : 'bg-amber-500'}`}
                    style={{ width: `${result.gradingCompleted ? 100 : 0}%` }}
                  />
                </div>
                <p className="text-[11px] text-gray-500">
                  {result.gradingCompleted ? '전체 채점 완료' : '예제 채점을 통과하면 진행'}
                </p>
              </div>
            </div>

            {/* 개별 결과 */}
            {result.details.filter((r) => r.isVisible).map((r, idx) => {
              const passed = r.status === "Correct";
              const isError = r.status === "Error";
              return (
              <div key={idx} className={`p-3 rounded-lg border ${
                passed ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5"
              }`}>
                <div className="flex items-center gap-2 mb-2">
                  {passed ? (
                    <CheckCircle size={14} className="text-green-400" />
                  ) : (
                    <XCircle size={14} className="text-red-400" />
                  )}
                  <span className="text-xs font-semibold text-gray-300">
                    예제 #{idx + 1}
                  </span>
                  <span className="text-[10px] text-blue-300 ml-auto uppercase tracking-wider">예제</span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <p className="text-gray-500 mb-0.5">입력</p>
                    <code className="block bg-[#1e1e1e] rounded px-2 py-1 text-gray-300 whitespace-pre-wrap">{r.input || "(없음)"}</code>
                  </div>
                  <div>
                    <p className="text-gray-500 mb-0.5">기대 출력</p>
                    <code className="block bg-[#1e1e1e] rounded px-2 py-1 text-green-300 whitespace-pre-wrap">{r.expected}</code>
                  </div>
                  <div>
                    <p className="text-gray-500 mb-0.5">실제 출력</p>
                    <code className={`block bg-[#1e1e1e] rounded px-2 py-1 whitespace-pre-wrap ${
                      passed ? "text-green-300" : "text-red-300"
                    }`}>{r.actual || "(없음)"}</code>
                  </div>
                </div>
                {isError && (
                  <p className="text-xs text-red-400 mt-2">오류: {r.actual || "실행 중 오류가 발생했습니다."}</p>
                )}
              </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
