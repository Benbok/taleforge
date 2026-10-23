import { expect, it } from 'vitest';
import { compareCounts, formatCount } from './counts';

it('compares and displays integers above JavaScript precision exactly', () => {
  expect(compareCounts('9007199254740993', '9007199254740992')).toBe(1);
  expect(compareCounts('100', '100')).toBe(0);
  expect(compareCounts('9', '10')).toBe(-1);
  expect(formatCount('9007199254740993').replace(/\s/g, '')).toBe('9007199254740993');
});
