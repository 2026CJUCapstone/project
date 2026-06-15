import {
  Activity,
  BadgeCheck,
  Code2,
  Medal,
  Sparkles,
  Tags,
  Trophy,
  TrendingUp,
} from 'lucide-react';
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts';
import type { ReactNode } from 'react';
import { getProblemTagLabel } from '../constants/problemTags';
import { DIFFICULTY_LEVELS } from '../services/problemApi';
import type { LeaderboardProfile } from '../services/leaderboardProfile';

const TIER_THRESHOLDS = [
  { min: 0, tier: 'Unrated' },
  { min: 30, tier: 'Iron V' },
  { min: 60, tier: 'Iron IV' },
  { min: 90, tier: 'Iron III' },
  { min: 120, tier: 'Iron II' },
  { min: 150, tier: 'Iron I' },
  { min: 200, tier: 'Bronze V' },
  { min: 300, tier: 'Bronze IV' },
  { min: 400, tier: 'Bronze III' },
  { min: 500, tier: 'Bronze II' },
  { min: 650, tier: 'Bronze I' },
  { min: 800, tier: 'Silver V' },
  { min: 950, tier: 'Silver IV' },
  { min: 1100, tier: 'Silver III' },
  { min: 1250, tier: 'Silver II' },
  { min: 1400, tier: 'Silver I' },
  { min: 1600, tier: 'Gold V' },
  { min: 1700, tier: 'Gold IV' },
  { min: 1800, tier: 'Gold III' },
  { min: 1900, tier: 'Gold II' },
  { min: 2100, tier: 'Gold I' },
  { min: 2200, tier: 'Platinum V' },
  { min: 2300, tier: 'Platinum IV' },
  { min: 2400, tier: 'Platinum III' },
  { min: 2500, tier: 'Platinum II' },
  { min: 2600, tier: 'Platinum I' },
  { min: 2700, tier: 'Diamond V' },
  { min: 2800, tier: 'Diamond IV' },
  { min: 2850, tier: 'Diamond III' },
  { min: 2900, tier: 'Diamond II' },
  { min: 2950, tier: 'Diamond I' },
  { min: 3000, tier: 'Master' },
];

const difficultyValue: Map<string, number> = new Map(DIFFICULTY_LEVELS.map((difficulty, index) => [difficulty, index + 1]));

function fallbackSolvedBonus(solvedCount: number) {
  if (solvedCount <= 0) return 0;
  return Math.round(200 * (1 - (0.997 ** solvedCount)));
}

function getTierAccent(tier: string) {
  if (tier.startsWith('Master')) return { text: 'text-fuchsia-400', bar: 'from-fuchsia-500 to-pink-500', glow: 'shadow-fuchsia-500/30' };
  if (tier.startsWith('Diamond')) return { text: 'text-sky-300', bar: 'from-sky-400 to-cyan-300', glow: 'shadow-sky-500/30' };
  if (tier.startsWith('Platinum')) return { text: 'text-cyan-300', bar: 'from-cyan-400 to-emerald-300', glow: 'shadow-cyan-500/25' };
  if (tier.startsWith('Gold')) return { text: 'text-yellow-300', bar: 'from-yellow-400 to-amber-500', glow: 'shadow-yellow-500/25' };
  if (tier.startsWith('Silver')) return { text: 'text-slate-200', bar: 'from-slate-300 to-slate-500', glow: 'shadow-slate-500/20' };
  if (tier.startsWith('Bronze')) return { text: 'text-amber-500', bar: 'from-amber-500 to-orange-700', glow: 'shadow-amber-500/20' };
  if (tier.startsWith('Iron')) return { text: 'text-zinc-300', bar: 'from-zinc-400 to-zinc-600', glow: 'shadow-zinc-500/20' };
  return { text: 'text-gray-400', bar: 'from-gray-500 to-gray-600', glow: 'shadow-gray-500/20' };
}

function getProgress(rating: number) {
  const current = [...TIER_THRESHOLDS].reverse().find((tier) => rating >= tier.min) ?? TIER_THRESHOLDS[0];
  const next = TIER_THRESHOLDS.find((tier) => tier.min > rating);
  if (!next) {
    return { current, next: null, percent: 100, remaining: 0 };
  }
  const span = next.min - current.min;
  const percent = span > 0 ? ((rating - current.min) / span) * 100 : 100;
  return {
    current,
    next,
    percent: Math.max(0, Math.min(100, percent)),
    remaining: Math.max(0, next.min - rating),
  };
}

function formatDifficulty(difficulty?: string | null) {
  if (!difficulty) return '기록 없음';
  return difficulty.replace(/([a-z]+)(\d+)/i, (_value, family: string, level: string) => {
    const label = family.charAt(0).toUpperCase() + family.slice(1);
    return `${label} ${level}`;
  });
}

function DifficultyBadge({ difficulty }: { difficulty: string }) {
  const value = difficultyValue.get(difficulty) ?? 0;
  const family = difficulty.replace(/\d+$/, '');
  const level = difficulty.match(/\d+$/)?.[0] ?? String(value);
  const colorClass = family === 'diamond'
    ? 'border-sky-300/60 bg-sky-400 text-sky-950'
    : family === 'platinum'
      ? 'border-cyan-300/60 bg-cyan-400 text-cyan-950'
      : family === 'gold'
        ? 'border-yellow-300/60 bg-yellow-400 text-yellow-950'
        : family === 'silver'
          ? 'border-slate-200/60 bg-slate-300 text-slate-950'
          : family === 'bronze'
            ? 'border-amber-500/60 bg-amber-600 text-white'
            : 'border-zinc-300/60 bg-zinc-500 text-white';

  return (
    <span
      title={formatDifficulty(difficulty)}
      className={`inline-flex h-6 min-w-6 items-center justify-center rounded-md border px-1.5 font-mono text-[11px] font-black shadow-sm ${colorClass}`}
    >
      {level}
    </span>
  );
}

function StatPill({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {icon}
        {label}
      </div>
      <div className="font-mono text-xl font-bold text-white">{value}</div>
    </div>
  );
}

export function ProfileStatsPanel({ user }: { user: LeaderboardProfile }) {
  const rating = user.rating ?? 0;
  const solvedCount = user.solvedCount ?? 0;
  const totalScore = user.totalScore ?? 0;
  const tier = user.tier ?? 'Unrated';
  const difficultyScore = user.difficultyScore ?? Math.max(0, rating - fallbackSolvedBonus(solvedCount));
  const solvedBonus = user.solvedBonus ?? fallbackSolvedBonus(solvedCount);
  const topDifficulties = user.topDifficulties ?? [];
  const tagProficiencies = user.tagProficiencies ?? [];
  const totalTagSolves = tagProficiencies.reduce((sum, item) => sum + item.solvedCount, 0) || solvedCount || 1;
  const progress = getProgress(rating);
  const accent = getTierAccent(tier);
  const radarData = tagProficiencies.slice(0, 8).map((item) => ({
    tag: getProblemTagLabel(item.tag),
    score: item.difficultyScore,
  }));

  return (
    <section className="overflow-hidden rounded-xl border border-slate-700 bg-[#05080d] text-white shadow-2xl">
      <div className="relative border-b border-slate-800 px-6 pb-6 pt-8">
        <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-r from-fuchsia-500/20 via-sky-500/10 to-emerald-500/20" />
        <div className="relative flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div className="flex items-end gap-4">
            <div className={`relative h-24 w-24 rounded-full border-4 border-slate-900 bg-slate-900 shadow-xl ${accent.glow}`}>
              <img src={user.avatar} alt={user.name} className="h-full w-full rounded-full object-cover" />
              <div className="absolute -bottom-3 left-1/2 flex h-10 w-10 -translate-x-1/2 items-center justify-center rounded-md bg-fuchsia-600 font-mono text-lg font-black text-white shadow-lg shadow-fuchsia-600/40">
                {Math.max(0, Math.min(9, Math.floor(solvedCount / 4)))}
              </div>
            </div>
            <div>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h3 className="text-3xl font-black tracking-tight">{user.name}</h3>
                <span className="rounded-md border border-sky-400/30 bg-sky-400/10 px-2 py-1 font-mono text-xs font-bold text-sky-300">
                  {solvedCount.toLocaleString()} solved
                </span>
                <span className="rounded-md border border-fuchsia-400/30 bg-fuchsia-400/10 px-2 py-1 font-mono text-xs font-bold text-fuchsia-300">
                  {tagProficiencies.length} tags
                </span>
              </div>
              <p className={`text-sm font-bold ${accent.text}`}>{tier} {rating.toLocaleString()}</p>
              <div className="mt-3 h-3 w-full min-w-[280px] overflow-hidden rounded-full bg-slate-700 md:w-[520px]">
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${accent.bar}`}
                  style={{ width: `${progress.percent}%` }}
                />
              </div>
              <p className="mt-2 text-xs text-slate-400">
                {progress.next ? `${progress.next.tier} 승급까지 ${progress.remaining.toLocaleString()}` : '최고 티어 구간입니다.'}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3 text-right">
            <StatPill icon={<Trophy size={14} />} label="Rating" value={rating.toLocaleString()} />
            <StatPill icon={<BadgeCheck size={14} />} label="XP" value={totalScore.toLocaleString()} />
            <StatPill icon={<Tags size={14} />} label="Tags" value={tagProficiencies.length.toLocaleString()} />
          </div>
        </div>
      </div>

      <div className="grid gap-5 p-6">
        <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-5">
          <div className="mb-5 flex items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-slate-400">
                <TrendingUp size={16} />
                B++ Rating
              </div>
              <p className={`mt-2 text-3xl font-black ${accent.text}`}>{tier} {rating.toLocaleString()}</p>
            </div>
            <div className="rounded-full bg-slate-800 px-5 py-3 text-right">
              <p className="font-mono text-lg font-black">#{rating > 0 ? '1' : '-'}</p>
              <p className="text-xs text-slate-400">현재 서비스 순위</p>
            </div>
          </div>

          <div className="mb-6 flex flex-wrap gap-2">
            {topDifficulties.length > 0 ? (
              topDifficulties.slice(0, 100).map((difficulty, index) => (
                <DifficultyBadge key={`${difficulty}-${index}`} difficulty={difficulty} />
              ))
            ) : (
              <span className="rounded-md border border-dashed border-slate-700 px-3 py-2 text-sm text-slate-500">
                accepted 기록이 없습니다.
              </span>
            )}
          </div>

          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between gap-4">
              <span className="text-slate-300">상위 100문제의 난이도 합</span>
              <span className="font-mono text-lg font-bold text-white">+ {difficultyScore.toLocaleString()}</span>
            </div>
            <div className="flex items-center justify-between gap-4">
              <span className="text-slate-300">{solvedCount.toLocaleString()}문제 해결 보너스</span>
              <span className="font-mono text-lg font-bold text-white">+ {solvedBonus.toLocaleString()}</span>
            </div>
            <div className="border-t border-dashed border-slate-700 pt-3">
              <div className="flex items-center justify-between gap-4">
                <span className="font-bold uppercase tracking-wide text-slate-300">Overall Rating</span>
                <span className="font-mono text-xl font-black text-white">{rating.toLocaleString()}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-5">
          <div className="mb-4 flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-slate-400">
            <Activity size={16} />
            태그 분포
          </div>
          <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
            <div className="h-[280px]">
              {radarData.length >= 3 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={radarData}>
                    <PolarGrid stroke="#243244" />
                    <PolarAngleAxis dataKey="tag" tick={{ fill: '#e2e8f0', fontSize: 12 }} />
                    <PolarRadiusAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} />
                    <Radar dataKey="score" stroke="#ff0066" fill="#ff0066" fillOpacity={0.18} />
                  </RadarChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-700 text-center text-sm text-slate-500">
                  태그가 3개 이상이면 레이더 차트가 표시됩니다.
                </div>
              )}
            </div>

            <div className="space-y-3">
              {tagProficiencies.length > 0 ? tagProficiencies.slice(0, 10).map((item) => {
                const share = (item.solvedCount / totalTagSolves) * 100;
                return (
                  <div key={item.tag} className="grid grid-cols-[minmax(0,1fr)_72px_72px_84px] items-center gap-3 text-sm">
                    <div className="min-w-0 truncate font-semibold text-white">
                      #{getProblemTagLabel(item.tag)}
                    </div>
                    <div className="text-right font-mono text-slate-200">{item.solvedCount}</div>
                    <div className="text-right font-mono text-slate-400">{share.toFixed(1)}%</div>
                    <div className="flex items-center justify-end gap-2 font-mono font-black text-emerald-300">
                      <DifficultyBadge difficulty={item.maxDifficulty ?? 'iron5'} />
                      {item.difficultyScore}
                    </div>
                  </div>
                );
              }) : (
                <div className="rounded-lg border border-dashed border-slate-700 p-5 text-center text-sm text-slate-500">
                  문제를 해결하면 태그별 숙련도가 여기에 표시됩니다.
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 border-t border-slate-800 p-6 md:grid-cols-4">
        <StatPill icon={<Medal size={14} />} label="Tier" value={tier} />
        <StatPill icon={<Code2 size={14} />} label="Solved" value={solvedCount.toLocaleString()} />
        <StatPill icon={<Sparkles size={14} />} label="Difficulty" value={difficultyScore.toLocaleString()} />
        <StatPill icon={<Activity size={14} />} label="Bonus" value={solvedBonus.toLocaleString()} />
      </div>
    </section>
  );
}
