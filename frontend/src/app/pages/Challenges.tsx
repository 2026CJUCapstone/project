import { useState, useMemo, useEffect } from 'react';
import { PlayCircle, Target, BookOpen, AlertTriangle, Code2, Tag, ChevronDown, ChevronUp, Loader2 } from 'lucide-react';
import { useNavigate } from 'react-router';
import { getProblems } from '../services/problemApi';
import type { ProblemTag } from '../services/problemApi';

type Difficulty = 'beginner' | 'intermediate' | 'advanced';
type ChallengeTag = ProblemTag;

interface Challenge {
  id: string;
  title: string;
  difficulty: Difficulty;
  tags: ChallengeTag[];
  description: string;
  expectedOutput?: string;
  failurePoints?: string[];
  testCases?: { input: string; expectedOutput: string }[];
}

const difficultyLabels: Record<Difficulty, string> = {
  beginner: '초급',
  intermediate: '중급',
  advanced: '고급'
};

const tagLabels: Record<ChallengeTag, string> = {
  io: '입출력',
  control: '제어문',
  func: '함수'
};

const difficultyColors = {
  beginner: 'text-green-400 bg-green-400/10 border-green-400/20',
  intermediate: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  advanced: 'text-red-400 bg-red-400/10 border-red-400/20'
};

const tagColors = {
  io: 'text-blue-300 bg-blue-500/10 border-blue-500/20',
  control: 'text-purple-300 bg-purple-500/10 border-purple-500/20',
  func: 'text-pink-300 bg-pink-500/10 border-pink-500/20'
};

function ChallengeCard({ challenge }: { challenge: Challenge }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const navigate = useNavigate();

  return (
    <div className={`flex flex-col rounded-xl border transition-all duration-300 overflow-hidden ${
      isExpanded ? 'bg-white dark:bg-[#1e1e1e] border-gray-300 dark:border-[#444] shadow-lg' : 'bg-gray-50 dark:bg-[#161616] border-gray-200 dark:border-[#333] hover:border-gray-300 dark:hover:border-[#555] hover:bg-white dark:hover:bg-[#1a1a1a]'
    }`}>
      {/* Header section (always visible) */}
      <div className="p-5 cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-4"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-2">
            <span className={`px-2.5 py-1 rounded-md text-xs font-semibold border uppercase tracking-wider ${difficultyColors[challenge.difficulty]}`}>
              {difficultyLabels[challenge.difficulty]}
            </span>
            {challenge.tags.map(tag => (
              <span key={tag} className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border ${tagColors[tag]}`}>
                <Tag size={12} />
                {tagLabels[tag]}
              </span>
            ))}
          </div>
          <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-2">{challenge.title}</h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-2">
            {challenge.description}
          </p>
        </div>
        
        <div className="flex items-center gap-4 shrink-0 justify-end md:justify-start mt-2 md:mt-0">
          <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 dark:hover:bg-blue-500 text-white text-sm font-semibold rounded-lg transition-colors shadow-sm"
                  onClick={(e) => { 
                    e.stopPropagation(); 
                    // IDE 화면으로 이동하면서 상태로 challenge 정보를 넘깁니다.
                    navigate('/', { state: { challenge } }); 
                  }}>
            <PlayCircle size={16} />
            문제 풀기
          </button>
          <div className="text-gray-500 p-2 rounded-full hover:bg-gray-100 dark:hover:bg-[#333] transition-colors">
            {isExpanded ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
          </div>
        </div>
      </div>

      {/* Expanded details section */}
      {isExpanded && (
        <div className="px-5 pb-5 border-t border-gray-200 dark:border-[#333] bg-gray-50 dark:bg-[#1a1a1a] pt-4 flex flex-col gap-5 animate-in slide-in-from-top-2 fade-in duration-200 transition-colors">
          {challenge.expectedOutput && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Target size={16} className="text-blue-600 dark:text-blue-400" />
                <h4 className="text-sm font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wider">기대 출력</h4>
              </div>
              <div className="bg-white dark:bg-[#0d0d0d] border border-gray-200 dark:border-[#333] rounded-lg p-3 font-mono text-sm text-green-600 dark:text-green-400 break-words shadow-inner">
                {challenge.expectedOutput}
              </div>
            </div>
          )}
          
          {challenge.failurePoints && challenge.failurePoints.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={16} className="text-red-600 dark:text-red-400" />
                <h4 className="text-sm font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wider">자주 틀리는 포인트</h4>
              </div>
              <ul className="space-y-2">
                {challenge.failurePoints.map((point, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-gray-600 dark:text-gray-400">
                    <span className="text-red-500 mt-0.5">•</span>
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Challenges() {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterDifficulty, setFilterDifficulty] = useState<Difficulty | 'all'>('all');
  const [filterTag, setFilterTag] = useState<ChallengeTag | 'all'>('all');

  useEffect(() => {
    getProblems()
      .then((problems) => {
        const mapped: Challenge[] = problems.map((p) => ({
          id: p.id,
          title: p.title,
          difficulty: p.difficulty,
          tags: p.tags ?? [],
          description: p.description,
          testCases: p.testCases,
        }));
        setChallenges(mapped);
      })
      .catch(() => {
        setChallenges([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const filteredChallenges = useMemo(() => {
    return challenges.filter(c => {
      const matchDiff = filterDifficulty === 'all' || c.difficulty === filterDifficulty;
      const matchTag = filterTag === 'all' || c.tags.includes(filterTag);
      return matchDiff && matchTag;
    });
  }, [challenges, filterDifficulty, filterTag]);

  return (
    <div className="w-full h-full flex flex-col bg-white dark:bg-[#121212] overflow-hidden transition-colors duration-200">
      {/* Header */}
      <div className="flex flex-col items-center justify-center py-8 bg-gray-50 dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0 relative transition-colors duration-200">
        <div className="flex items-center gap-3 mb-3">
          <BookOpen className="text-blue-600 dark:text-blue-500" size={32} />
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-wide">챌린지 허브</h1>
        </div>
        <p className="text-gray-600 dark:text-gray-400 text-sm mb-6 max-w-lg text-center leading-relaxed">
          엄선된 문제들을 통해 B++ 실력을 향상시키세요.<br/>
          난이도나 주제별로 필터링하고, 자주 틀리는 부분을 확인하며 언어를 마스터해보세요.
        </p>

        {/* Filters */}
        <div className="flex flex-wrap items-center justify-center gap-4">
          <div className="flex items-center gap-2 bg-white dark:bg-[#0d0d0d] p-1 rounded-lg border border-gray-200 dark:border-[#333] transition-colors">
            <span className="px-3 text-xs font-semibold text-gray-500 uppercase">난이도</span>
            <div className="h-4 w-px bg-gray-200 dark:bg-[#333]" />
            <select 
              value={filterDifficulty} 
              onChange={(e) => setFilterDifficulty(e.target.value as any)}
              className="bg-transparent text-sm text-gray-700 dark:text-gray-300 px-2 py-1 outline-none cursor-pointer"
            >
              <option value="all">모든 난이도</option>
              <option value="beginner">초급</option>
              <option value="intermediate">중급</option>
              <option value="advanced">고급</option>
            </select>
          </div>

          <div className="flex items-center gap-2 bg-white dark:bg-[#0d0d0d] p-1 rounded-lg border border-gray-200 dark:border-[#333] transition-colors">
            <span className="px-3 text-xs font-semibold text-gray-500 uppercase">태그</span>
            <div className="h-4 w-px bg-gray-200 dark:bg-[#333]" />
            <select 
              value={filterTag} 
              onChange={(e) => setFilterTag(e.target.value as any)}
              className="bg-transparent text-sm text-gray-700 dark:text-gray-300 px-2 py-1 outline-none cursor-pointer"
            >
              <option value="all">모든 주제</option>
              <option value="io">입출력</option>
              <option value="control">제어문</option>
              <option value="func">함수</option>
            </select>
          </div>
        </div>
      </div>

      {/* Challenge List */}
      <div className="flex-1 overflow-y-auto p-6 relative">
        <div className="max-w-5xl mx-auto flex flex-col gap-4 pb-12">
          {loading ? (
            <div className="flex flex-col items-center justify-center py-20">
              <Loader2 size={32} className="animate-spin text-blue-500 mb-3" />
              <p className="text-gray-500 text-sm">문제를 불러오는 중...</p>
            </div>
          ) : filteredChallenges.length > 0 ? (
            filteredChallenges.map(challenge => (
              <ChallengeCard key={challenge.id} challenge={challenge} />
            ))
          ) : (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Code2 size={48} className="text-gray-300 dark:text-[#333] mb-4" />
              <h3 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-2">조건에 맞는 챌린지가 없습니다</h3>
              <p className="text-gray-500 text-sm">필터를 조정하여 다른 결과를 확인해보세요.</p>
              <button 
                onClick={() => { setFilterDifficulty('all'); setFilterTag('all'); }}
                className="mt-6 px-4 py-2 bg-white dark:bg-[#2d2d2d] hover:bg-gray-50 dark:hover:bg-[#3d3d3d] text-gray-700 dark:text-white rounded-lg text-sm transition-colors border border-gray-200 dark:border-[#444] shadow-sm"
              >
                필터 초기화
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
