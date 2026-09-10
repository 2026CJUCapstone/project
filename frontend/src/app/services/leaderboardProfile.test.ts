import { beforeEach, expect, it } from 'vitest';
import { getSavedLeaderboardProfile, profileFromAuthUser, saveLeaderboardProfile } from './leaderboardProfile';

beforeEach(() => localStorage.clear());

it('keeps the editable null avatar separate from the generated display avatar through caching', () => {
  const profile = profileFromAuthUser({ id: 'u1', username: 'user', nickname: null, avatarUrl: null });
  expect(profile.name).toBe('user');
  expect(profile.avatar).toContain('dicebear');
  expect(profile.avatarUrl).toBeNull();
  saveLeaderboardProfile(profile);
  expect(getSavedLeaderboardProfile()?.avatarUrl).toBeNull();
});

it('preserves a custom editable avatar through mapping and caching', () => {
  const profile = profileFromAuthUser({ id: 'u1', username: 'user', avatarUrl: 'https://fixture.invalid/a.svg' });
  expect(profile.avatarUrl).toBe('https://fixture.invalid/a.svg');
  saveLeaderboardProfile(profile);
  expect(getSavedLeaderboardProfile()?.avatarUrl).toBe(profile.avatar);
});
