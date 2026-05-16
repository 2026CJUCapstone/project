import { useState, useMemo, useEffect } from 'react';
import { PlayCircle, Code2, Tag, Loader2, Search, RotateCcw } from 'lucide-react';
import { useNavigate } from 'react-router';
import { DIFFICULTY_LEVELS, getProblems } from '../services/problemApi';
import type { ProblemTag, ProblemDifficulty } from '../services/problemApi';
import { DIFFICULTY_LABELS, getDifficultyBadgeClass } from '../constants/difficulty';

type Difficulty = ProblemDifficulty;
type ChallengeTag = ProblemTag;
type SortOption = 'difficultyAsc' | 'difficultyDesc' | 'title';

interface Challenge {
  id: string;
  title: string;
  difficulty: Difficulty;
  tags: ChallengeTag[];
  description: string;
  testCases?: { input: string; expectedOutput: string }[];
}

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

const difficultyTrackStops: Difficulty[] = [
  'iron5',
  'bronze5',
  'silver5',
  'gold5',
  'platinum5',
  'diamond5',
  'diamond1',
];

function getProblemSummary(description: string): string {
  const normalized = description.replace(/\r\n/g, '\n');
  const problemMatch = normalized.match(/##\s*문제\s*\n+([\s\S]*?)(\n##\s*입력|\n##\s*출력|$)/);
  const source = problemMatch?.[1] ?? normalized;
  return source
    .replace(/#{1,6}\s/g, '')
    .replace(/`/g, '')
    .replace(/\n+/g, ' ')
    .trim();
}

function ChallengeRow({ challenge, index }: { challenge: Challenge; index: number }) {
  const navigate = useNavigate();

  return (
    <div className="grid grid-cols-[56px_120px_1fr_220px_140px] gap-3 items-center px-4 py-3 border-b border-gray-200 dark:border-[#242424] hover:bg-gray-50/80 dark:hover:bg-[#191919] transition-colors">
      <div className="text-sm text-gray-500">{index + 1}</div>
      <div>
        <span className={`inline-flex px-2 py-0.5 rounded-md text-xs font-semibold border ${getDifficultyBadgeClass(challenge.difficulty)}`}>
          {DIFFICULTY_LABELS[challenge.difficulty] ?? challenge.difficulty}
        </span>
      </div>
      <button
        type="button"
        onClick={() => navigate(`/challenges/${challenge.id}`)}
        className="text-left"
      >
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
          {challenge.title}
        </h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-1 mt-1">{getProblemSummary(challenge.description)}</p>
      </button>
      <div className="flex flex-wrap gap-1.5">
        {challenge.tags.map((tag) => (
          <span key={tag} className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${tagColors[tag]}`}>
            <Tag size={10} />
            {tagLabels[tag]}
          </span>
        ))}
      </div>
      <div className="flex justify-end">
        <button
          className="inline-flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-md transition-colors"
          onClick={() => navigate('/', { state: { challenge } })}
        >
          <PlayCircle size={14} />
          문제 풀기
        </button>
      </div>
    </div>
  );
}

export function Challenges() {
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [minDifficulty, setMinDifficulty] = useState<Difficulty>('iron5');
  const [maxDifficulty, setMaxDifficulty] = useState<Difficulty>('diamond1');
  const [selectedTags, setSelectedTags] = useState<Set<ChallengeTag>>(new Set());
  const [sortBy, setSortBy] = useState<SortOption>('difficultyAsc');

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
    const keyword = searchText.trim().toLowerCase();
    const minIndex = DIFFICULTY_LEVELS.indexOf(minDifficulty);
    const maxIndex = DIFFICULTY_LEVELS.indexOf(maxDifficulty);

    const filtered = challenges.filter((challenge) => {
      const matchKeyword =
        keyword.length === 0 ||
        challenge.title.toLowerCase().includes(keyword) ||
        getProblemSummary(challenge.description).toLowerCase().includes(keyword);

      const challengeIndex = DIFFICULTY_LEVELS.indexOf(challenge.difficulty);
      const matchDifficulty = challengeIndex >= minIndex && challengeIndex <= maxIndex;

      const matchTag =
        selectedTags.size === 0 ||
        challenge.tags.some((tag) => selectedTags.has(tag));

      return matchKeyword && matchDifficulty && matchTag;
    });

    return filtered.sort((a, b) => {
      if (sortBy === 'title') {
        return a.title.localeCompare(b.title, 'ko');
      }

      const aIndex = DIFFICULTY_LEVELS.indexOf(a.difficulty);
      const bIndex = DIFFICULTY_LEVELS.indexOf(b.difficulty);
      return sortBy === 'difficultyAsc' ? aIndex - bIndex : bIndex - aIndex;
    });
  }, [challenges, searchText, minDifficulty, maxDifficulty, selectedTags, sortBy]);

  const toggleTag = (tag: ChallengeTag) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  };

  const resetFilters = () => {
    setSearchText('');
    setMinDifficulty('iron5');
    setMaxDifficulty('diamond1');
    setSelectedTags(new Set());
    setSortBy('difficultyAsc');
  };

  return (
    <div className="w-full h-full bg-white dark:bg-[#121212] text-gray-900 dark:text-gray-100 overflow-hidden">
      <div className="h-full grid grid-cols-1 lg:grid-cols-[300px_1fr]">
        <aside className="border-r border-gray-200 dark:border-[#333] bg-gray-50 dark:bg-[#1e1e1e] overflow-y-auto">
          <div className="p-5 space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold tracking-wide">필터</h2>
              <button
                onClick={resetFilters}
                className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
              >
                <RotateCcw size={12} />
                초기화
              </button>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500">검색</label>
              <div className="mt-2 relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                <input
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  placeholder="문제 제목/설명 검색"
                  className="w-full pl-9 pr-3 py-2 rounded-md border border-gray-300 dark:border-[#333] bg-white dark:bg-[#0d0d0d] text-sm outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-gray-500 mb-3">난이도</div>
              <div className="px-3 py-4 rounded-lg border border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616]">
                <div className="relative mb-2">
                  {/* Slider Track */}
                  <div className="relative h-1 bg-gray-300 dark:bg-[#444] rounded-full">
                    <div
                      className="absolute h-1 bg-blue-500 rounded-full top-0"
                      style={{
                        left: `${(DIFFICULTY_LEVELS.indexOf(minDifficulty) / (DIFFICULTY_LEVELS.length - 1)) * 100}%`,
                        right: `${100 - (DIFFICULTY_LEVELS.indexOf(maxDifficulty) / (DIFFICULTY_LEVELS.length - 1)) * 100}%`,
                      }}
                    />
                  </div>

                  {/* Range Inputs */}
                  <div className="relative h-5 pointer-events-none -mt-3">
                    <input
                      type="range"
                      min="0"
                      max={DIFFICULTY_LEVELS.length - 1}
                      value={DIFFICULTY_LEVELS.indexOf(minDifficulty)}
                      onChange={(e) => {
                        const newIndex = parseInt(e.target.value, 10);
                        const newMin = DIFFICULTY_LEVELS[newIndex];
                        if (DIFFICULTY_LEVELS.indexOf(newMin) <= DIFFICULTY_LEVELS.indexOf(maxDifficulty)) {
                          setMinDifficulty(newMin);
                        }
                      }}
                      className="absolute w-full h-full top-0 left-0 pointer-events-none appearance-none bg-transparent cursor-pointer z-4 [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-blue-500 [&::-webkit-slider-thumb]:cursor-grab [&::-webkit-slider-thumb]:shadow-sm [&::-webkit-slider-thumb]:active:cursor-grabbing [&::-webkit-slider-track]:bg-transparent [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-blue-500 [&::-moz-range-thumb]:cursor-grab [&::-moz-range-thumb]:shadow-sm [&::-moz-range-thumb]:active:cursor-grabbing [&::-moz-range-track]:bg-transparent"
                    />
                    <input
                      type="range"
                      min="0"
                      max={DIFFICULTY_LEVELS.length - 1}
                      value={DIFFICULTY_LEVELS.indexOf(maxDifficulty)}
                      onChange={(e) => {
                        const newIndex = parseInt(e.target.value, 10);
                        const newMax = DIFFICULTY_LEVELS[newIndex];
                        if (DIFFICULTY_LEVELS.indexOf(newMax) >= DIFFICULTY_LEVELS.indexOf(minDifficulty)) {
                          setMaxDifficulty(newMax);
                        }
                      }}
                      className="absolute w-full h-full top-0 left-0 pointer-events-none appearance-none bg-transparent cursor-pointer z-5 [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-blue-500 [&::-webkit-slider-thumb]:cursor-grab [&::-webkit-slider-thumb]:shadow-sm [&::-webkit-slider-thumb]:active:cursor-grabbing [&::-webkit-slider-track]:bg-transparent [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:w-3.5 [&::-moz-range-thumb]:h-3.5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-blue-500 [&::-moz-range-thumb]:cursor-grab [&::-moz-range-thumb]:shadow-sm [&::-moz-range-thumb]:active:cursor-grabbing [&::-moz-range-track]:bg-transparent"
                    />
                  </div>

                  {/* Difficulty Tier Badges Below Track */}
                  <div className="relative h-7 -mt-1">
                    <div className="absolute inset-0 flex items-start" style={{ width: '100%', paddingLeft: 0, paddingRight: 0 }}>
                      {difficultyTrackStops.map((difficulty) => {
                        const percentage = (DIFFICULTY_LEVELS.indexOf(difficulty) / (DIFFICULTY_LEVELS.length - 1)) * 100;
                        return (
                          <div
                            key={difficulty}
                            className="flex flex-col items-center gap-0.5"
                            style={{
                              position: 'absolute',
                              left: `${percentage}%`,
                              transform: 'translateX(-50%)',
                            }}
                          >
                            <div className="w-0.5 h-0.5 bg-gray-400 dark:bg-gray-500" />
                            <span className={`inline-flex px-1 py-0.5 rounded text-[8px] font-semibold border whitespace-nowrap ${getDifficultyBadgeClass(difficulty)}`}>
                              {DIFFICULTY_LABELS[difficulty].split(' ')[1]}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                <div className="text-center pt-0">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">
                    {DIFFICULTY_LABELS[minDifficulty]} ~ {DIFFICULTY_LABELS[maxDifficulty]}
                  </p>
                </div>
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-gray-500 mb-2">태그</div>
              <div className="flex flex-wrap gap-2">
                {(Object.keys(tagLabels) as ChallengeTag[]).map((tag) => {
                  const active = selectedTags.has(tag);
                  return (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => toggleTag(tag)}
                      className={`px-2.5 py-1 rounded-md border text-xs transition-colors ${
                        active
                          ? tagColors[tag]
                          : 'border-gray-300 dark:border-[#333] text-gray-600 dark:text-gray-300 hover:border-blue-400'
                      }`}
                    >
                      {tagLabels[tag]}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500">정렬</label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as SortOption)}
                className="w-full mt-2 px-3 py-2 rounded-md border border-gray-300 dark:border-[#333] bg-white dark:bg-[#0d0d0d] text-sm outline-none focus:border-blue-500"
              >
                <option value="difficultyAsc">난이도 낮은 순</option>
                <option value="difficultyDesc">난이도 높은 순</option>
                <option value="title">제목순</option>
              </select>
            </div>
          </div>
        </aside>

        <section className="h-full overflow-y-auto">
          <div className="p-6">
            <div className="mb-4 flex items-center justify-between">
              <h1 className="text-xl font-bold">문제 목록</h1>
              <p className="text-sm text-gray-500">{filteredChallenges.length}문제</p>
            </div>

            {loading ? (
              <div className="flex flex-col items-center justify-center py-20">
                <Loader2 size={32} className="animate-spin text-blue-500 mb-3" />
                <p className="text-gray-500 text-sm">문제를 불러오는 중...</p>
              </div>
            ) : filteredChallenges.length > 0 ? (
              <div className="rounded-xl border border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616] overflow-x-auto">
                <div className="min-w-[860px]">
                  <div className="grid grid-cols-[56px_120px_1fr_220px_140px] gap-3 px-4 py-3 border-b border-gray-200 dark:border-[#242424] text-xs font-semibold text-gray-500">
                    <div>#</div>
                    <div>난이도</div>
                    <div>제목</div>
                    <div>태그</div>
                    <div className="text-right">실행</div>
                  </div>
                  {filteredChallenges.map((challenge, index) => (
                    <ChallengeRow key={challenge.id} challenge={challenge} index={index} />
                  ))}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <Code2 size={48} className="text-gray-300 dark:text-[#333] mb-4" />
                <h3 className="text-lg font-bold text-gray-700 dark:text-gray-300 mb-2">조건에 맞는 챌린지가 없습니다</h3>
                <p className="text-gray-500 text-sm">필터를 조정하여 다른 결과를 확인해보세요.</p>
                <button
                  onClick={resetFilters}
                  className="mt-6 px-4 py-2 bg-white dark:bg-[#2d2d2d] hover:bg-gray-50 dark:hover:bg-[#3d3d3d] text-gray-700 dark:text-white rounded-lg text-sm transition-colors border border-gray-200 dark:border-[#444] shadow-sm"
                >
                  필터 초기화
                </button>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
