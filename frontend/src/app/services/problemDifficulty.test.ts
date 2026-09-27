import { describe, expect, it } from 'vitest';
import { DIFFICULTY_LABELS, getDifficultyBadgeClass } from '../constants/difficulty';
import { DIFFICULTY_LEVELS } from './problemApi';

const LEGACY_DIFFICULTIES = [
  'iron5', 'iron4', 'iron3', 'iron2', 'iron1',
  'bronze5', 'bronze4', 'bronze3', 'bronze2', 'bronze1',
  'silver5', 'silver4', 'silver3', 'silver2', 'silver1',
  'gold5', 'gold4', 'gold3', 'gold2', 'gold1',
  'platinum5', 'platinum4', 'platinum3', 'platinum2', 'platinum1',
  'diamond5', 'diamond4', 'diamond3', 'diamond2', 'diamond1',
];
const RUBY_DIFFICULTIES = ['ruby5', 'ruby4', 'ruby3', 'ruby2', 'ruby1'];

describe('problem difficulty constants', () => {
  it('appends Ruby after every existing difficulty without moving filter indices', () => {
    expect(DIFFICULTY_LEVELS).toEqual([...LEGACY_DIFFICULTIES, ...RUBY_DIFFICULTIES]);
    expect(DIFFICULTY_LEVELS.indexOf('diamond1')).toBe(29);
    expect(DIFFICULTY_LEVELS.indexOf('ruby5')).toBe(30);
    expect(DIFFICULTY_LEVELS.indexOf('ruby1')).toBe(34);
  });

  it('labels and colors each Ruby difficulty as a problem difficulty', () => {
    expect(DIFFICULTY_LABELS.ruby5).toBe('루비 5');
    expect(DIFFICULTY_LABELS.ruby1).toBe('루비 1');
    expect(getDifficultyBadgeClass('ruby3')).toContain('rose');
  });
});
