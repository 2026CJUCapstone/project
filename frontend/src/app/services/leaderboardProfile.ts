import type { TagProficiency } from './authApi';

export interface LeaderboardProfile {
  name: string;
  avatar: string;
  id?: string;
  username?: string;
  email?: string | null;
  nickname?: string | null;
  role?: 'user' | 'admin' | string;
  totalScore?: number;
  rating?: number;
  tier?: string;
  solvedCount?: number;
  difficultyScore?: number;
  solvedBonus?: number;
  topDifficulties?: string[];
  tagProficiencies?: TagProficiency[];
}

const USER_STORAGE_KEY = 'b-compiler-user';
const GUEST_STORAGE_KEY = 'b-compiler-guest-profile';

function canUseStorage() {
  return typeof window !== 'undefined' && Boolean(window.localStorage);
}

function safeParseProfile(value: string | null): LeaderboardProfile | null {
  if (!value) return null;

  try {
    const parsed = JSON.parse(value) as Partial<LeaderboardProfile>;
    if (typeof parsed.name !== 'string' || typeof parsed.avatar !== 'string') {
      return null;
    }
    const tagProficiencies = Array.isArray(parsed.tagProficiencies)
      ? parsed.tagProficiencies.filter(
        (item): item is TagProficiency =>
          typeof item === 'object' &&
          item !== null &&
          typeof item.tag === 'string' &&
          typeof item.solvedCount === 'number' &&
          typeof item.difficultyScore === 'number' &&
          typeof item.maxDifficultyValue === 'number' &&
          typeof item.proficiency === 'number',
      )
      : undefined;
    const topDifficulties = Array.isArray(parsed.topDifficulties)
      ? parsed.topDifficulties.filter((item): item is string => typeof item === 'string')
      : undefined;
    return {
      name: parsed.name,
      avatar: parsed.avatar,
      id: typeof parsed.id === 'string' ? parsed.id : undefined,
      username: typeof parsed.username === 'string' ? parsed.username : undefined,
      email: typeof parsed.email === 'string' ? parsed.email : null,
      nickname: typeof parsed.nickname === 'string' ? parsed.nickname : null,
      role: typeof parsed.role === 'string' ? parsed.role : undefined,
      totalScore: typeof parsed.totalScore === 'number' ? parsed.totalScore : undefined,
      rating: typeof parsed.rating === 'number' ? parsed.rating : undefined,
      tier: typeof parsed.tier === 'string' ? parsed.tier : undefined,
      solvedCount: typeof parsed.solvedCount === 'number' ? parsed.solvedCount : undefined,
      difficultyScore: typeof parsed.difficultyScore === 'number' ? parsed.difficultyScore : undefined,
      solvedBonus: typeof parsed.solvedBonus === 'number' ? parsed.solvedBonus : undefined,
      topDifficulties,
      tagProficiencies,
    };
  } catch {
    return null;
  }
}

export function createAvatarUrl(seed: string) {
  return `https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(seed)}&backgroundColor=transparent`;
}

export function saveLeaderboardProfile(profile: LeaderboardProfile) {
  if (!canUseStorage()) return;
  window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(profile));
}

export function profileFromAuthUser(user: {
  id: string;
  username: string;
  email?: string | null;
  nickname?: string | null;
  avatarUrl?: string | null;
  role?: string;
  totalScore?: number;
  rating?: number;
  tier?: string;
  solvedCount?: number;
  difficultyScore?: number;
  solvedBonus?: number;
  topDifficulties?: string[];
  tagProficiencies?: TagProficiency[];
}): LeaderboardProfile {
  const name = user.nickname?.trim() || user.username;
  return {
    id: user.id,
    username: user.username,
    email: user.email ?? null,
    nickname: user.nickname ?? null,
    name,
    avatar: user.avatarUrl || createAvatarUrl(name),
    role: user.role ?? 'user',
    totalScore: user.totalScore,
    rating: user.rating,
    tier: user.tier,
    solvedCount: user.solvedCount,
    difficultyScore: user.difficultyScore,
    solvedBonus: user.solvedBonus,
    topDifficulties: user.topDifficulties,
    tagProficiencies: user.tagProficiencies,
  };
}

export function getSavedLeaderboardProfile(): LeaderboardProfile | null {
  if (!canUseStorage()) return null;
  return safeParseProfile(window.localStorage.getItem(USER_STORAGE_KEY));
}

export function clearLeaderboardProfile() {
  if (!canUseStorage()) return;
  window.localStorage.removeItem(USER_STORAGE_KEY);
}

export function getLeaderboardProfile(): LeaderboardProfile {
  if (!canUseStorage()) {
    return { name: 'Guest Coder', avatar: createAvatarUrl('Guest Coder') };
  }

  const savedUser = safeParseProfile(window.localStorage.getItem(USER_STORAGE_KEY));
  if (savedUser) return savedUser;

  const savedGuest = safeParseProfile(window.localStorage.getItem(GUEST_STORAGE_KEY));
  if (savedGuest) return savedGuest;

  const suffix = Math.random().toString(36).slice(2, 8).toUpperCase();
  const guest = {
    name: `Guest_${suffix}`,
    avatar: createAvatarUrl(`guest-${suffix}`),
  };
  window.localStorage.setItem(GUEST_STORAGE_KEY, JSON.stringify(guest));
  return guest;
}
