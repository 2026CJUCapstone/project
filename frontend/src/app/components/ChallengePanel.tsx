import { useState } from "react";
import { ChevronDown, ChevronUp, BookOpen } from "lucide-react";
import { JudgePanel } from "./JudgePanel";
import type { TestCase } from "../services/problemApi";

interface Challenge {
  id: string;
  title: string;
  difficulty: string;
  tags?: string[];
  description: string;
  expectedOutput?: string;
  failurePoints?: string[];
  testCases?: TestCase[];
}

const difficultyLabels: Record<string, string> = {
  beginner: "초급",
  intermediate: "중급",
  advanced: "고급",
};

const difficultyColors: Record<string, string> = {
  beginner: "text-green-400 bg-green-400/10 border-green-400/20",
  intermediate: "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
  advanced: "text-red-400 bg-red-400/10 border-red-400/20",
};

interface Props {
  challenge: Challenge;
  code: string;
  onClose: () => void;
}

export function ChallengePanel({ challenge, code, onClose }: Props) {
  const [judgeOpen, setJudgeOpen] = useState(false);

  const testCases: TestCase[] =
    challenge.testCases ??
    [{ input: "", expectedOutput: challenge.expectedOutput ?? "" }];

  return (
    <div className="flex flex-col h-full bg-[#0d0d0d] text-gray-100 overflow-hidden">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-[#1e1e1e] border-b border-[#333] shrink-0">
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-blue-400" />
          <span className="text-xs font-semibold uppercase tracking-widest text-gray-200">문제</span>
        </div>
        <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200 transition-colors">
          닫기
        </button>
      </div>

      {/* 문제 설명 영역 */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-4 flex flex-col gap-3">
          {/* 제목 + 난이도 */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${difficultyColors[challenge.difficulty] ?? "text-gray-400 bg-gray-400/10 border-gray-400/20"}`}>
                {difficultyLabels[challenge.difficulty] ?? challenge.difficulty}
              </span>
              {challenge.tags?.map((tag) => (
                <span key={tag} className="px-2 py-0.5 rounded text-xs font-medium border text-blue-300 bg-blue-500/10 border-blue-500/20">
                  {tag}
                </span>
              ))}
            </div>
            <h2 className="text-lg font-bold text-white">{challenge.title}</h2>
          </div>

          {/* 설명 */}
          <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
            {challenge.description}
          </p>

          {/* 기대 출력 */}
          {challenge.expectedOutput && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">기대 출력</p>
              <code className="block bg-[#1a1a1a] border border-[#333] rounded px-3 py-2 text-sm text-green-400 whitespace-pre-wrap">
                {challenge.expectedOutput}
              </code>
            </div>
          )}

          {/* 자주 틀리는 포인트 */}
          {challenge.failurePoints && challenge.failurePoints.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">자주 틀리는 포인트</p>
              <ul className="flex flex-col gap-1">
                {challenge.failurePoints.map((point, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-xs text-gray-400">
                    <span className="text-red-400 mt-0.5">•</span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* 채점 접기/펼치기 */}
        <div className="border-t border-[#333]">
          <button
            onClick={() => setJudgeOpen(!judgeOpen)}
            className="flex items-center justify-between w-full px-4 py-2.5 hover:bg-[#1a1a1a] transition-colors"
          >
            <span className="text-xs font-semibold text-green-400 uppercase tracking-widest">채점하기</span>
            {judgeOpen ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
          </button>

          {judgeOpen && (
            <div className="border-t border-[#333]">
              <JudgePanel
                code={code}
                challengeTitle={challenge.title}
                testCases={testCases}
                onClose={() => setJudgeOpen(false)}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
