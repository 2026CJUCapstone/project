import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Crown, Loader2, Medal, RefreshCw, Trophy, Users } from 'lucide-react';
import { getLeaderboard, type LeaderboardEntry } from '../services/problemApi';

const LEADERBOARD_LIMIT = 50;

function getAvatarUrl(entry: LeaderboardEntry) {
  if (entry.avatarUrl) return entry.avatarUrl;
  return `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(entry.username)}&backgroundColor=transparent`;
}

function getRankIcon(rank: number) {
  switch (rank) {
    case 1:
      return <Crown className="text-yellow-500" size={24} />;
    case 2:
      return <Medal className="text-gray-400" size={24} />;
    case 3:
      return <Medal className="text-amber-600" size={24} />;
    default:
      return <span className="w-6 text-center text-sm font-bold text-gray-500 dark:text-gray-400">{rank}</span>;
  }
}

export function Leaderboard() {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadLeaderboard = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);

    try {
      const data = await getLeaderboard(LEADERBOARD_LIMIT);
      setEntries(data);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '리더보드를 불러오지 못했습니다.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadLeaderboard();
  }, [loadLeaderboard]);

  const topEntry = entries[0];
  const totalScore = useMemo(
    () => entries.reduce((sum, entry) => sum + entry.totalScore, 0),
    [entries],
  );

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-gray-50 text-gray-900 transition-colors duration-200 dark:bg-[#121212] dark:text-white">
      <div className="shrink-0 border-b border-gray-200 bg-white px-6 py-7 transition-colors duration-200 dark:border-[#333] dark:bg-[#1e1e1e]">
        <div className="mx-auto flex max-w-5xl flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="mb-3 flex items-center gap-3">
              <Trophy className="text-yellow-600 dark:text-yellow-500" size={32} />
              <h1 className="text-2xl font-bold">리더보드</h1>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              챌린지를 통과해 획득한 누적 XP 기준 순위입니다.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 dark:border-[#333] dark:bg-[#151515]">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">전체 랭킹</p>
              <p className="mt-1 text-lg font-bold">{entries.length.toLocaleString()}명</p>
            </div>
            <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 dark:border-[#333] dark:bg-[#151515]">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">누적 XP</p>
              <p className="mt-1 text-lg font-bold text-blue-600 dark:text-blue-400">{totalScore.toLocaleString()}</p>
            </div>
            <button
              onClick={() => void loadLeaderboard()}
              disabled={isLoading}
              className="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-700 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-[#444] dark:bg-[#252525] dark:text-gray-200 dark:hover:bg-[#333]"
            >
              <RefreshCw size={16} className={isLoading ? 'animate-spin' : ''} />
              새로고침
            </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-6">
        <div className="mx-auto flex max-w-5xl flex-col gap-5 pb-10">
          {topEntry && (
            <div className="grid gap-4 rounded-lg border border-yellow-500/30 bg-yellow-50 px-5 py-4 dark:bg-yellow-500/10 md:grid-cols-[1fr_auto] md:items-center">
              <div className="flex items-center gap-4">
                <img
                  src={getAvatarUrl(topEntry)}
                  alt={`${topEntry.username} avatar`}
                  className="h-14 w-14 rounded-full border border-yellow-500/40 bg-white dark:bg-[#1e1e1e]"
                />
                <div>
                  <p className="text-xs font-semibold text-yellow-700 dark:text-yellow-400">현재 1위</p>
                  <p className="mt-1 text-xl font-bold">{topEntry.username}</p>
                </div>
              </div>
              <div className="text-left md:text-right">
                <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">점수</p>
                <p className="mt-1 font-mono text-2xl font-bold text-blue-600 dark:text-blue-400">
                  {topEntry.totalScore.toLocaleString()} XP
                </p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-[72px_minmax(0,1fr)_128px] border-b border-gray-200 px-4 py-3 text-xs font-semibold text-gray-500 dark:border-[#333] dark:text-gray-400">
            <div className="text-center">순위</div>
            <div>사용자</div>
            <div className="text-right">점수</div>
          </div>

          {isLoading && (
            <div className="flex min-h-[260px] flex-col items-center justify-center gap-3 text-gray-500 dark:text-gray-400">
              <Loader2 size={28} className="animate-spin text-blue-600 dark:text-blue-400" />
              <p className="text-sm font-medium">리더보드를 불러오는 중입니다.</p>
            </div>
          )}

          {!isLoading && errorMessage && (
            <div className="flex min-h-[260px] flex-col items-center justify-center gap-3 rounded-lg border border-red-500/30 bg-red-50 px-6 text-center text-red-700 dark:bg-red-500/10 dark:text-red-300">
              <AlertCircle size={28} />
              <p className="text-sm font-semibold">{errorMessage}</p>
              <button
                onClick={() => void loadLeaderboard()}
                className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-red-500"
              >
                다시 시도
              </button>
            </div>
          )}

          {!isLoading && !errorMessage && entries.length === 0 && (
            <div className="flex min-h-[260px] flex-col items-center justify-center gap-3 rounded-lg border border-gray-200 bg-white px-6 text-center dark:border-[#333] dark:bg-[#1a1a1a]">
              <Users size={30} className="text-blue-600 dark:text-blue-400" />
              <div>
                <p className="font-bold text-gray-900 dark:text-white">아직 등록된 점수가 없습니다.</p>
                <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
                  챌린지를 만점으로 통과하면 첫 순위가 만들어집니다.
                </p>
              </div>
            </div>
          )}

          {!isLoading && !errorMessage && entries.map((entry) => (
            <div
              key={`${entry.rank}-${entry.username}`}
              className={`grid grid-cols-[72px_minmax(0,1fr)_128px] items-center rounded-lg border px-4 py-3 transition-colors ${
                entry.rank <= 3
                  ? 'border-gray-200 bg-white shadow-sm hover:border-blue-500/50 dark:border-[#333] dark:bg-[#1a1a1a] dark:hover:border-blue-500/60'
                  : 'border-transparent bg-transparent hover:border-gray-200 hover:bg-white dark:hover:border-[#333] dark:hover:bg-[#1a1a1a]'
              }`}
            >
              <div className="flex items-center justify-center">{getRankIcon(entry.rank)}</div>
              <div className="flex min-w-0 items-center gap-4">
                <img
                  src={getAvatarUrl(entry)}
                  alt={`${entry.username} avatar`}
                  className="h-10 w-10 shrink-0 rounded-full bg-gray-100 dark:bg-[#2d2d2d]"
                />
                <span className={`truncate font-semibold ${entry.rank <= 3 ? 'text-lg text-gray-900 dark:text-white' : 'text-gray-700 dark:text-gray-300'}`}>
                  {entry.username}
                </span>
              </div>
              <div className="text-right font-mono font-bold text-blue-600 dark:text-blue-400">
                {entry.totalScore.toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
