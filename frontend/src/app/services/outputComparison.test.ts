import { describe, expect, it } from 'vitest';
import { compareOutput } from './outputComparison';

describe('compareOutput', () => {
  it('matches identical output and clears difference details', () => {
    expect(compareOutput('hello\nworld', 'hello\nworld')).toEqual({
      matches: true,
      firstDifferentLine: null,
      actualLine: null,
      expectedLine: null,
    });
  });

  it('normalizes CRLF and CR line endings in both modes', () => {
    expect(compareOutput('one\r\ntwo\rthree', 'one\ntwo\nthree')).toEqual({
      matches: true,
      firstDifferentLine: null,
      actualLine: null,
      expectedLine: null,
    });
    expect(compareOutput('one\r\ntwo', 'one\ntwo', 'exact').matches).toBe(true);
  });

  it('ignores trailing spaces, tabs, and trailing empty lines in trim-lines mode', () => {
    expect(compareOutput('  one  \n\n two\t\n\n', '  one\n\n two')).toEqual({
      matches: true,
      firstDifferentLine: null,
      actualLine: null,
      expectedLine: null,
    });
    expect(compareOutput('', '\n\n')).toEqual({
      matches: true,
      firstDifferentLine: null,
      actualLine: null,
      expectedLine: null,
    });
  });

  it('preserves leading whitespace and blank lines in the middle', () => {
    expect(compareOutput('  value', 'value')).toEqual({
      matches: false,
      firstDifferentLine: 1,
      actualLine: '  value',
      expectedLine: 'value',
    });
    expect(compareOutput('first\n\nlast', 'first\nlast')).toEqual({
      matches: false,
      firstDifferentLine: 2,
      actualLine: '',
      expectedLine: 'last',
    });
  });

  it('reports missing and extra lines with null for the missing side', () => {
    expect(compareOutput('same', 'same\nnext')).toEqual({
      matches: false,
      firstDifferentLine: 2,
      actualLine: null,
      expectedLine: 'next',
    });
    expect(compareOutput('same\nnext', 'same')).toEqual({
      matches: false,
      firstDifferentLine: 2,
      actualLine: 'next',
      expectedLine: null,
    });
  });

  it('keeps exact mode sensitive to trailing newlines and whitespace', () => {
    expect(compareOutput('line', 'line\n', 'exact')).toEqual({
      matches: false,
      firstDifferentLine: 2,
      actualLine: null,
      expectedLine: '',
    });
    expect(compareOutput('line ', 'line', 'exact')).toEqual({
      matches: false,
      firstDifferentLine: 1,
      actualLine: 'line ',
      expectedLine: 'line',
    });
    expect(compareOutput('line ', 'line', 'trim-lines').matches).toBe(true);
  });

  it('compares unicode and literal HTML as ordinary text', () => {
    expect(compareOutput('안녕 🌍\n<div>ok</div>', '안녕 🌍\n<div>ok</div>')).toEqual({
      matches: true,
      firstDifferentLine: null,
      actualLine: null,
      expectedLine: null,
    });
    expect(compareOutput('<b>x</b>', '<b>y</b>')).toEqual({
      matches: false,
      firstDifferentLine: 1,
      actualLine: '<b>x</b>',
      expectedLine: '<b>y</b>',
    });
  });
});
