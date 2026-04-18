export interface LeaderboardProfile {
  name: string;
  avatar: string;
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
    return { name: parsed.name, avatar: parsed.avatar };
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
