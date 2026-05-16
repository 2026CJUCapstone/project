
import { useState } from "react";
import { useNavigate } from "react-router";
import { ChevronDown, ChevronUp, BookOpen, MessageSquare } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { JudgePanel } from "./JudgePanel";
import type { TestCase } from "../services/problemApi";
import { DIFFICULTY_LABELS, getDifficultyBadgeClass } from "../constants/difficulty";
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

interface Props {
  challenge: Challenge;
  code: string;
  onClose?: () => void;
}

export function ChallengePanel({ challenge, code, onClose }: Props) {
  const [judgeOpen, setJudgeOpen] = useState(false);
  const navigate = useNavigate();

  const goToCommunity = () => {
    navigate('/community', {
      state: {
        tab: 'problems',
        problemId: challenge.id,
        problemTitle: challenge.title,
      },
    });
  };

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
        <div className="flex items-center gap-2">
          <button
            onClick={goToCommunity}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-purple-300 hover:text-white hover:bg-purple-500/20 border border-purple-500/30 transition-colors"
            title="이 문제의 커뮤니티로 이동"
          >
            <MessageSquare size={12} />
            커뮤니티
          </button>
          {onClose && (
            <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200 transition-colors">
              닫기
            </button>
          )}
        </div>
      </div>

      {/* 문제 설명 영역 */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-4 flex flex-col gap-3">
          {/* 제목 + 난이도 */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${getDifficultyBadgeClass(challenge.difficulty)}`}>
                {DIFFICULTY_LABELS[challenge.difficulty as keyof typeof DIFFICULTY_LABELS] ?? challenge.difficulty}
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
          <div className="prose prose-sm max-w-none prose-invert prose-headings:text-white prose-p:text-gray-300 prose-strong:text-gray-100 prose-code:text-blue-300 prose-pre:bg-[#1a1a1a] prose-pre:border prose-pre:border-[#333]">
            <ReactMarkdown
              remarkPlugins={[remarkMath]}
              rehypePlugins={[rehypeKatex]}
            >
              {challenge.description}
            </ReactMarkdown>
          </div>
          {/* 기대 출력 */}
          {testCases.length > 0 && (
            <div className="flex flex-col gap-3">
              {testCases.map((testCase, index) => (
                <div key={index} className="rounded-lg border border-[#333] bg-[#111] p-3">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">예시 {index + 1}</p>
                  <div className="grid grid-cols-1 gap-3">
                    <div>
                      <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">입력</p>
                      <code className="block bg-[#1a1a1a] border border-[#333] rounded px-3 py-2 text-sm text-gray-300 whitespace-pre-wrap">
                        {testCase.input || "(없음)"}
                      </code>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">출력</p>
                      <code className="block bg-[#1a1a1a] border border-[#333] rounded px-3 py-2 text-sm text-green-400 whitespace-pre-wrap">
                        {testCase.expectedOutput || "(없음)"}
                      </code>
                    </div>
                  </div>
                </div>
              ))}
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
                challengeId={challenge.id}
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
