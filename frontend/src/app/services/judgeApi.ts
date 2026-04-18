import { executeCode } from './compilerApi';
import type { ExecuteRequest } from './compilerApi';

export interface JudgeResult {
  testIndex: number;
  input: string;
  expectedOutput: string;
  actualOutput: string;
  expected: string;
  actual: string;
  passed: boolean;
  executionTime?: number;
  error?: string;
}

export interface JudgeSummary {
  results: JudgeResult[];
  totalCount: number;
  passedCount: number;
  allPassed: boolean;
}

export async function judgeCode(
  code: string,
  testCases: { input: string; expectedOutput: string }[]
): Promise<JudgeSummary> {
  const results: JudgeResult[] = [];

  for (let i = 0; i < testCases.length; i++) {
    const tc = testCases[i];
    try {
      const request: ExecuteRequest = { code, input: tc.input };
      const response = await executeCode(request);
      const actualOutput = (response.stdout ?? '').trim();
      const expectedOutput = tc.expectedOutput.trim();
      results.push({
        testIndex: i + 1,
        input: tc.input,
        expectedOutput,
        actualOutput,
        expected: expectedOutput,
        actual: actualOutput,
        passed: actualOutput === expectedOutput,
      });
    } catch {
      results.push({
        testIndex: i + 1,
        input: tc.input,
        expectedOutput: tc.expectedOutput.trim(),
        actualOutput: '실행 오류',
        expected: tc.expectedOutput.trim(),
        actual: '실행 오류',
        passed: false,
        error: '실행 오류',
      });
    }
  }

  const passedCount = results.filter((r) => r.passed).length;
  return {
    results,
    totalCount: testCases.length,
    passedCount,
    allPassed: passedCount === testCases.length,
  };
}
