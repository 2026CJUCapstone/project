import type { ProblemDifficulty } from '../services/problemApi';

export const DIFFICULTY_LABELS: Record<ProblemDifficulty, string> = {
  iron5: '아이언 5',
  iron4: '아이언 4',
  iron3: '아이언 3',
  iron2: '아이언 2',
  iron1: '아이언 1',
  bronze5: '브론즈 5',
  bronze4: '브론즈 4',
  bronze3: '브론즈 3',
  bronze2: '브론즈 2',
  bronze1: '브론즈 1',
  silver5: '실버 5',
  silver4: '실버 4',
  silver3: '실버 3',
  silver2: '실버 2',
  silver1: '실버 1',
  gold5: '골드 5',
  gold4: '골드 4',
  gold3: '골드 3',
  gold2: '골드 2',
  gold1: '골드 1',
  platinum5: '플래티넘 5',
  platinum4: '플래티넘 4',
  platinum3: '플래티넘 3',
  platinum2: '플래티넘 2',
  platinum1: '플래티넘 1',
  diamond5: '다이아 5',
  diamond4: '다이아 4',
  diamond3: '다이아 3',
  diamond2: '다이아 2',
  diamond1: '다이아 1',
};

export function getDifficultyBadgeClass(difficulty: string): string {
  if (difficulty.startsWith('iron')) return 'text-zinc-300 bg-zinc-500/10 border-zinc-500/30';
  if (difficulty.startsWith('bronze')) return 'text-amber-300 bg-amber-600/10 border-amber-600/30';
  if (difficulty.startsWith('silver')) return 'text-slate-300 bg-slate-500/10 border-slate-500/30';
  if (difficulty.startsWith('gold')) return 'text-yellow-300 bg-yellow-500/10 border-yellow-500/30';
  if (difficulty.startsWith('platinum')) return 'text-cyan-300 bg-cyan-500/10 border-cyan-500/30';
  if (difficulty.startsWith('diamond')) return 'text-blue-300 bg-blue-500/10 border-blue-500/30';
  return 'text-gray-300 bg-gray-500/10 border-gray-500/30';
}
