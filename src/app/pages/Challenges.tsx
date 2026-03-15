import { useState, useMemo } from 'react';
import { PlayCircle, Target, BookOpen, AlertTriangle, Code2, Tag, ChevronDown, ChevronUp } from 'lucide-react';
import { useNavigate } from 'react-router';

type Difficulty = 'beginner' | 'intermediate' | 'advanced';
type ChallengeTag = 'io' | 'control' | 'func';

interface Challenge {
  id: string;
  title: string;
  difficulty: Difficulty;
  tags: ChallengeTag[];
  description: string;
  expectedOutput: string;
  failurePoints: string[];
}

const mockChallenges: Challenge[] = [
  {
    id: 'c1',
    title: 'B++로 "Hello, World!" 출력하기',
    difficulty: 'beginner',
    tags: ['io'],
    description: '표준 출력으로 "Hello, World!"를 정확하게 출력하는 프로그램을 작성하세요. B++ 학습의 첫 걸음입니다.',
    expectedOutput: 'Hello, World!',
    failurePoints: [
      '마지막에 느낌표(!)를 빼먹는 경우',
      '소문자 "h"나 "w"를 사용하는 경우',
      '엄격한 채점 환경에서 개행 문자(줄바꿈)를 생략하는 경우'
    ]
  },
  {
    id: 'c2',
    title: '홀수와 짝수',
    difficulty: 'beginner',
    tags: ['control', 'io'],
    description: '표준 입력에서 정수를 읽어옵니다. 숫자가 짝수면 "Even", 홀수면 "Odd"를 출력하세요.',
    expectedOutput: 'Even (입력이 4인 경우)\nOdd (입력이 7인 경우)',
    failurePoints: [
      '음수를 제대로 처리하지 못하는 경우',
      '입력이 "0"일 때 짝수로 처리하지 않는 경우'
    ]
  },
  {
    id: 'c3',
    title: '피보나치 수열',
    difficulty: 'intermediate',
    tags: ['control', 'func'],
    description: '정수 N을 받아 피보나치 수열의 처음 N개 숫자를 출력하는 함수를 구현하세요.',
    expectedOutput: '0 1 1 2 3 5 8 13... (N=8인 경우)',
    failurePoints: [
      'N이 클 때 최적화되지 않은 재귀를 사용하여 스택 오버플로우가 발생하는 경우',
      'N=0 또는 N=1일 때 잘못된 출력이 나오는 경우',
      '숫자 사이에 공백을 넣어 형식을 맞추지 않은 경우'
    ]
  },
  {
    id: 'c4',
    title: '소인수분해',
    difficulty: 'intermediate',
    tags: ['control', 'io'],
    description: '주어진 정수의 소인수를 오름차순으로 계산하여 출력하세요.',
    expectedOutput: '2 2 3 5 (입력이 60인 경우)',
    failurePoints: [
      '소수에서 무한 루프에 빠지는 경우',
      '2보다 작은 입력을 처리하지 못하는 경우',
      '동일한 소인수가 여러 번 나올 때 하나만 출력하는 경우'
    ]
  },
  {
    id: 'c5',
    title: '커스텀 그래프 탐색',
    difficulty: 'advanced',
    tags: ['func', 'control'],
    description: '커스텀 그래프 구조에서 깊이 우선 탐색(DFS)을 구현하세요. 그래프는 표준 입력을 통해 인접 리스트 형태로 제공됩니다.',
    expectedOutput: '0 1 3 4 2 (그래프 구조에 따라 다름)',
    failurePoints: [
      '방문한 노드를 추적하지 않아 사이클에서 무한 루프에 빠지는 경우',
      '단절된 그래프를 제대로 처리하지 못하는 경우',
      '메모리 누수나 비효율적인 재귀 깊이 문제'
    ]
  },
  {
    id: 'c6',
    title: '고차 함수 Mapper',
    difficulty: 'advanced',
    tags: ['func'],
    description: '배열과 콜백 함수를 인자로 받아, 모든 요소에 콜백을 적용한 새로운 배열을 반환하는 고차 함수를 작성하세요.',
    expectedOutput: '[2, 4, 6] (입력이 [1, 2, 3]이고 콜백이 x * 2인 경우)',
    failurePoints: [
      '새로운 배열을 반환하지 않고 원본 배열을 수정(Mutate)하는 경우',
      '빈 배열을 제대로 처리하지 못하는 경우',
      '엄격한 타입 환경에서 타입 추론 문제가 발생하는 경우'
    ]
  }
];

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
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Target size={16} className="text-blue-600 dark:text-blue-400" />
              <h4 className="text-sm font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wider">기대 출력</h4>
            </div>
            <div className="bg-white dark:bg-[#0d0d0d] border border-gray-200 dark:border-[#333] rounded-lg p-3 font-mono text-sm text-green-600 dark:text-green-400 break-words shadow-inner">
              {challenge.expectedOutput}
            </div>
          </div>
          
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
        </div>
      )}
    </div>
  );
}

export function Challenges() {
  const [filterDifficulty, setFilterDifficulty] = useState<Difficulty | 'all'>('all');
  const [filterTag, setFilterTag] = useState<ChallengeTag | 'all'>('all');

  const filteredChallenges = useMemo(() => {
    return mockChallenges.filter(c => {
      const matchDiff = filterDifficulty === 'all' || c.difficulty === filterDifficulty;
      const matchTag = filterTag === 'all' || c.tags.includes(filterTag);
      return matchDiff && matchTag;
    });
  }, [filterDifficulty, filterTag]);

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
          {filteredChallenges.length > 0 ? (
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
