import { expect, it } from 'vitest';
import { isStoredHiddenTestCase, type HiddenTestCase, type StoredHiddenTestCase, type TestCase } from './problemApi';

const digest = `sha256:${'a'.repeat(64)}` as `sha256:${string}`;
const stored: StoredHiddenTestCase = {
  kind: 'stored-v1',
  inputRef: { digest, byteCount: 512, encoding: 'utf-8' },
  expectedOutputRef: { digest, byteCount: 256, encoding: 'utf-8' },
};

it('allows persisted references only in the private hidden-test union', () => {
  const hidden: HiddenTestCase = stored;
  // @ts-expect-error Stored references are forbidden in public sample test cases.
  const publicSample: TestCase = stored;
  expect(isStoredHiddenTestCase(hidden)).toBe(true);
  expect(publicSample).toBe(stored);
});
