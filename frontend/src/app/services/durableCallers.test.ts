import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ submitExecution: vi.fn(), submitPracticeExecution: vi.fn() }));
vi.mock('./executionApi', () => mocks);

import { compileCode, executeCode } from './compilerApi';
import { submitProblem } from './problemApi';

describe('durable execution callers', () => {
  beforeEach(() => vi.clearAllMocks());

  it('maps compile and run requests to the durable snake-case contract', async () => {
    mocks.submitExecution
      .mockResolvedValueOnce({ success: true, execution_time: 12 })
      .mockResolvedValueOnce({ stdout: '42\n', stderr: '', exit_code: 0, execution_time: 8 });

    await expect(compileCode({ code: 'source', language: 'cpp', problemId: 'p1', options: { optimize: true, target: 'ir' } }))
      .resolves.toMatchObject({ success: true, executionTime: 12 });
    await expect(executeCode({ code: 'source', language: 'cpp', input: 'stdin', problemId: 'p1' }))
      .resolves.toMatchObject({ success: true, stdout: '42\n', executionTime: 8 });

    expect(mocks.submitExecution.mock.calls[0][0]).toEqual({
      source_code: 'source', language: 'cpp', optimize: true, problem_id: 'p1', kind: 'compile', target: 'ir',
    });
    expect(mocks.submitExecution.mock.calls[1][0]).toEqual({
      source_code: 'source', language: 'cpp', stdin: 'stdin', optimize: false, problem_id: 'p1', kind: 'run', target: 'all',
    });
  });

  it('keeps the practice submission value contract after asynchronous polling', async () => {
    const value = { verdict: 'wrong_answer', status: 'Rejected', details: [] };
    mocks.submitPracticeExecution.mockResolvedValue(value);

    await expect(submitProblem('problem/1', 'source', 'bpp')).resolves.toBe(value);
    expect(mocks.submitPracticeExecution).toHaveBeenCalledWith('problem/1', { code: 'source', language: 'bpp' });
  });
});
