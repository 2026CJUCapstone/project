import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { JudgePanel } from './JudgePanel';
import { useCompilerStore } from '../store/compilerStore';

const { submit } = vi.hoisted(() => ({ submit: vi.fn() }));
vi.mock('../services/problemApi', () => ({ submitProblem: submit }));
const initial = useCompilerStore.getState();
beforeEach(() => {
  submit.mockReset().mockRejectedValue(new Error('controlled receipt failure'));
  useCompilerStore.setState(initial, true);
});
afterEach(() => { cleanup(); useCompilerStore.setState(initial, true); });

it.each(['bpp', 'c', 'cpp', 'python', 'java', 'javascript'] as const)(
  'submits the selected %s language rather than a fixed B++ language', async language => {
    useCompilerStore.setState({ language });
    render(<JudgePanel code="current editor source" challengeId="problem-1" challengeTitle="Example" testCases={[]} onClose={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: '제출' }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith('problem-1', 'current editor source', language));
    await screen.findByText('controlled receipt failure');
  },
);

it('uses the new language and code after changing language while the judge panel stays open', async () => {
  useCompilerStore.setState({ language: 'bpp' });
  const { rerender } = render(<JudgePanel code="old source" challengeId="problem-1" challengeTitle="Example" testCases={[]} onClose={() => {}} />);
  act(() => useCompilerStore.setState({ language: 'python' }));
  rerender(<JudgePanel code="print(42)" challengeId="problem-1" challengeTitle="Example" testCases={[]} onClose={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: '제출' }));
  await waitFor(() => expect(submit).toHaveBeenCalledWith('problem-1', 'print(42)', 'python'));
  await screen.findByText('controlled receipt failure');
});

it.each([
  ['output_limit_exceeded', '출력 초과'],
  ['process_limit_exceeded', '프로세스 제한 초과'],
  ['compile_resource_error', '컴파일 자원 초과'],
] as const)('renders the public %s verdict label from a practice result', async (verdict, label) => {
  submit.mockResolvedValueOnce({
    status: 'Rejected', verdict, totalCases: 1, passedCases: 0, sampleTotalCases: 1, samplePassedCases: 0,
    gradingCompleted: true, gradingPassed: false, totalScore: 0, details: [], message: '',
  });
  render(<JudgePanel code="source" challengeId="problem-1" challengeTitle="Example" testCases={[]} onClose={() => {}} />);

  fireEvent.click(screen.getByRole('button', { name: '제출' }));

  expect(await screen.findByText(label)).toBeInTheDocument();
});
