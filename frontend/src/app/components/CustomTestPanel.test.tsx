import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CustomTestPanel } from './CustomTestPanel';
import { useCompilerStore } from '../store/compilerStore';
import { setAuthToken } from '../services/authIdentity';

const { execute } = vi.hoisted(() => ({ execute: vi.fn() }));

vi.mock('../services/compilerApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../services/compilerApi')>()),
  executeCode: execute,
}));

const initialState = useCompilerStore.getState();

beforeEach(() => {
  localStorage.clear();
  execute.mockReset();
  useCompilerStore.setState({
    ...initialState,
    code: 'print(input())',
    language: 'python',
    isEditorReady: true,
    isCompiling: false,
    isRunning: false,
    codeStorageOwner: 'guest',
  }, true);
});

afterEach(() => {
  cleanup();
  useCompilerStore.setState(initialState, true);
});

it('runs the captured editor code with stdin through the execution queue and shows the actual result', async () => {
  execute.mockResolvedValue({ success: true, stdout: 'echo: 42\n', stderr: '', exitCode: 0, executionTime: 12 });
  render(<CustomTestPanel />);

  fireEvent.change(screen.getByLabelText('표준 입력'), { target: { value: '42\n' } });
  fireEvent.click(screen.getByRole('button', { name: '테스트 실행' }));

  await waitFor(() => expect(execute).toHaveBeenCalledWith(
    { code: 'print(input())', language: 'python', input: '42\n' },
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  ));
  expect(await screen.findByTestId('custom-test-result')).toBeInTheDocument();
  expect(screen.getByTestId('custom-test-stdout')).toHaveTextContent('echo: 42');
  expect(screen.getByTestId('custom-test-stderr')).toHaveTextContent('(없음)');
  expect(screen.getByTestId('custom-test-exit-code')).toHaveTextContent('0');
  expect(screen.getByTestId('custom-test-execution-time')).toHaveTextContent('12ms');
});

it('compares output only as a user test and reports the first differing line', async () => {
  execute.mockResolvedValue({ success: true, stdout: 'one\ntwo\n', stderr: '', exitCode: 0, executionTime: 4 });
  render(<CustomTestPanel />);

  fireEvent.click(screen.getByRole('checkbox', { name: '예상 출력 비교' }));
  fireEvent.change(screen.getByLabelText('예상 출력'), { target: { value: 'one\nthree\n' } });
  fireEvent.click(screen.getByRole('button', { name: '테스트 실행' }));

  expect(await screen.findByText('사용자 테스트 비교: 출력 불일치')).toBeInTheDocument();
  expect(screen.getByText(/첫 차이: 2번째 줄/)).toHaveTextContent('실제: two, 예상: three');
  expect(screen.queryByText('정답')).not.toBeInTheDocument();
});

it('applies sample input and expected output for a user-controlled run', () => {
  render(<CustomTestPanel samples={[{ input: '3\n', expectedOutput: '9\n' }]} />);

  fireEvent.click(screen.getByRole('button', { name: '예제 1 적용' }));

  expect(screen.getByLabelText('표준 입력')).toHaveValue('3\n');
  expect(screen.getByRole('checkbox', { name: '예상 출력 비교' })).toBeChecked();
  expect(screen.getByLabelText('예상 출력')).toHaveValue('9\n');
});

it('does not display a completed response after the editor code changes', async () => {
  let resolveExecution!: (value: { success: boolean; stdout: string; stderr: string; exitCode: number; executionTime: number }) => void;
  execute.mockImplementation(() => new Promise((resolve) => { resolveExecution = resolve; }));
  render(<CustomTestPanel />);

  fireEvent.click(screen.getByRole('button', { name: '테스트 실행' }));
  act(() => useCompilerStore.setState({ code: 'print("new source")' }));
  await act(async () => { resolveExecution({ success: true, stdout: 'old output', stderr: '', exitCode: 0, executionTime: 1 }); });

  await waitFor(() => expect(screen.queryByTestId('custom-test-result')).not.toBeInTheDocument());
});

it('uses a single in-flight request and aborts it when the panel unmounts', () => {
  let receivedSignal: AbortSignal | undefined;
  execute.mockImplementation((_request: unknown, options: { signal?: AbortSignal }) => {
    receivedSignal = options.signal;
    return new Promise(() => {});
  });
  const { unmount } = render(<CustomTestPanel />);

  const runButton = screen.getByRole('button', { name: '테스트 실행' });
  fireEvent.click(runButton);
  fireEvent.click(runButton);
  expect(execute).toHaveBeenCalledTimes(1);

  unmount();
  expect(receivedSignal?.aborted).toBe(true);
});

it('blocks stdin above the backend UTF-8 byte cap', () => {
  render(<CustomTestPanel />);

  fireEvent.change(screen.getByLabelText('표준 입력'), { target: { value: '😀'.repeat(16_385) } });

  expect(screen.getByRole('button', { name: '테스트 실행' })).toBeDisabled();
  expect(screen.getByRole('alert')).toHaveTextContent('65,536 bytes');
  expect(execute).not.toHaveBeenCalled();
});

it('clears private input and aborts pending work even on same-account token replacement', async () => {
  const token = (nonce: number) => `header.${btoa(JSON.stringify({ sub: 'alice', nonce }))}.signature`;
  setAuthToken(token(1));
  useCompilerStore.setState({ codeStorageOwner: 'account:alice' });
  let resolve!: (value: object) => void;
  let signal!: AbortSignal;
  execute.mockImplementation((_request, options) => {
    signal = options.signal;
    return new Promise(r => { resolve = r; });
  });
  render(<CustomTestPanel />);
  fireEvent.change(screen.getByLabelText('표준 입력'), { target: { value: 'private input' } });
  fireEvent.click(screen.getByRole('button', { name: '테스트 실행' }));
  act(() => setAuthToken(token(2)));
  expect(signal.aborted).toBe(true);
  expect(screen.getByLabelText('표준 입력')).toHaveValue('');
  expect(screen.getByRole('button', { name: '테스트 실행' })).toBeEnabled();
  await act(async () => resolve({ stdout: 'private output', exitCode: 0 }));
  expect(screen.queryByTestId('custom-test-result')).not.toBeInTheDocument();
});
