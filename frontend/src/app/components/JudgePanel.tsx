import { useState } from "react";
import { CheckCircle, XCircle, Clock, Send } from "lucide-react";
import { judgeCode } from "../services/judgeApi";
import type { JudgeSummary } from "../services/judgeApi";
import type { TestCase } from "../services/problemApi";

interface Props {
  code: string;
  challengeTitle: string;
  testCases: TestCase[];
  onClose: () => void;
}

export function JudgePanel({ code, challengeTitle, testCases, onClose }: Props) {
  const [result, setResult] = useState<JudgeSummary | null>(null);
  const [isJudging, setIsJudging] = useState(false);

  const handleSubmit = async () => {
    setIsJudging(true);
    try {
      const res = await judgeCode(code, testCases);
      setResult(res);
    } catch {
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
            <p>제출 버튼을 눌러 코드를 채점하세요</p>
            <p className="text-xs mt-1 text-gray-600">테스트 케이스 {testCases.length}개</p>
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
              result.allPassed
                ? "bg-green-500/10 border-green-500/30"
                : "bg-red-500/10 border-red-500/30"
            }`}>
              {result.allPassed ? (
                <CheckCircle size={20} className="text-green-400" />
              ) : (
                <XCircle size={20} className="text-red-400" />
              )}
              <div>
                <p className={`text-sm font-bold ${result.allPassed ? "text-green-400" : "text-red-400"}`}>
                  {result.allPassed ? "정답입니다!" : "오답입니다"}
                </p>
                <p className="text-xs text-gray-400">
                  {result.passedCount}/{result.totalCount} 통과
                </p>
              </div>
            </div>

            {/* 개별 결과 */}
            {result.results.map((r, idx) => (
              <div key={idx} className={`p-3 rounded-lg border ${
                r.passed ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5"
              }`}>
                <div className="flex items-center gap-2 mb-2">
                  {r.passed ? (
                    <CheckCircle size={14} className="text-green-400" />
                  ) : (
                    <XCircle size={14} className="text-red-400" />
                  )}
                  <span className="text-xs font-semibold text-gray-300">
                    테스트 #{idx + 1}
                  </span>
                  <span className="text-xs text-gray-500 ml-auto">
                    {r.executionTime}ms
                  </span>
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
                      r.passed ? "text-green-300" : "text-red-300"
                    }`}>{r.actual || "(없음)"}</code>
                  </div>
                </div>
                {r.error && (
                  <p className="text-xs text-red-400 mt-2">오류: {r.error}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
