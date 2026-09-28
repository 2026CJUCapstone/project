import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OptimizationCompare } from './CompilerExplorer';
import { useCompilerStore } from '../store/compilerStore';
import { compileCode, type CompileResponse, type OptimizationSummary } from '../services/compilerApi';

vi.mock('../services/compilerApi', () => ({
  checkHealth: vi.fn(),
  compileCode: vi.fn(),
  executeCode: vi.fn(),
}));

const initialStore = useCompilerStore.getState();
const source = 'func main() -> u64 { return 0; }';

function result(optimizationLevel: number, success = true, optimizationSummaries?: OptimizationSummary[]): CompileResponse {
  return {
    success,
    executionTime: 1,
    metadata: { optimizationLevel },
    ssa: optimizationSummaries ? { blocks: [], edges: [], optimizationSummaries } : undefined,
    ir: { instructions: [{ id: `return-${optimizationLevel}`, opcode: 'return', operands: [] }] },
  };
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function renderCompare(props: Partial<React.ComponentProps<typeof OptimizationCompare>> = {}) {
  const defaults = {
    source,
    baseline: result(1),
    current: true,
    scope: 'problem:one',
    owner: 'account:alice',
  };
  return render(<OptimizationCompare {...defaults} {...props} />);
}

describe('OptimizationCompare', () => {
  beforeEach(() => {
    useCompilerStore.setState(initialStore, true);
    useCompilerStore.setState({ code: source, codeStorageScope: 'problem:one', codeStorageOwner: 'account:alice' });
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
    useCompilerStore.setState(initialStore, true);
  });

  it('requests optimization off and then on in order', async () => {
    const off = deferred<CompileResponse>();
    const on = deferred<CompileResponse>();
    vi.mocked(compileCode).mockImplementationOnce(() => off.promise).mockImplementationOnce(() => on.promise);
    const user = userEvent.setup();

    renderCompare();
    await user.click(screen.getByRole('button', { name: '최적화 전후 비교하기' }));

    expect(compileCode).toHaveBeenCalledTimes(1);
    expect(compileCode).toHaveBeenLastCalledWith(
      { code: source, language: 'bpp', problemId: 'one', options: { optimize: false, target: 'all' } },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await act(async () => {
      off.resolve(result(0));
    });
    await waitFor(() => expect(compileCode).toHaveBeenCalledTimes(2));
    expect(compileCode).toHaveBeenLastCalledWith(
      { code: source, language: 'bpp', problemId: 'one', options: { optimize: true, target: 'all' } },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await act(async () => {
      on.resolve(result(1));
    });
    expect(await screen.findByText(/1개 → 1개/)).toBeInTheDocument();
  });

  it('shows the optimization failure after the successful baseline request', async () => {
    vi.mocked(compileCode).mockResolvedValueOnce(result(0)).mockResolvedValueOnce(result(1, false));
    const user = userEvent.setup();

    renderCompare();
    await user.click(screen.getByRole('button', { name: '최적화 전후 비교하기' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('최적화 후 컴파일이 실패했습니다.');
    expect(compileCode).toHaveBeenCalledTimes(2);
  });

  it('shows only nonzero compiler-reported function-level optimization reasons', async () => {
    const summaries: OptimizationSummary[] = [
      {
        functionId: 'main',
        functionName: 'main',
        level: 1,
        scope: 'function',
        evidence: 'compiler-counters-v1',
        counters: { constantOperands: 2, unusedCopies: 0, deadStores: 1 },
      },
      {
        functionId: 'helper',
        functionName: 'helper',
        level: 1,
        scope: 'function',
        evidence: 'compiler-counters-v1',
        counters: { commonExpressions: 3 },
      },
    ];
    vi.mocked(compileCode).mockResolvedValueOnce(result(0)).mockResolvedValueOnce(result(1, true, summaries));
    const user = userEvent.setup();

    renderCompare();
    await user.click(screen.getByRole('button', { name: '최적화 전후 비교하기' }));

    expect(await screen.findByRole('region', { name: '함수 단위 최적화 보고' })).toHaveTextContent('컴파일러가 SSA 변환에서 함수별로 집계한 카운터입니다. 아래 이유는 개별 diff 줄에 귀속되지 않으며, IR·ASM의 줄별 변환 이유도 아닙니다.');
    expect(screen.getByText('상수로 확정된 피연산자 대체 · 2회')).toBeInTheDocument();
    expect(screen.getByText('불필요한 저장 제거 · 1회')).toBeInTheDocument();
    expect(screen.getByText('중복 계산 재사용 · 3회')).toBeInTheDocument();
    expect(screen.queryByText(/불필요한 복사 제거/)).not.toBeInTheDocument();
  });

  it('marks optimization reasons unavailable when the compiler supplies no function evidence', async () => {
    vi.mocked(compileCode).mockResolvedValueOnce(result(0)).mockResolvedValueOnce(result(1));
    const user = userEvent.setup();

    renderCompare();
    await user.click(screen.getByRole('button', { name: '최적화 전후 비교하기' }));

    expect(await screen.findByText('함수 단위 최적화 근거를 제공하지 않아 이유를 추정할 수 없습니다.')).toBeInTheDocument();
    expect(screen.queryByText(/상수 조건 분기 단순화/)).not.toBeInTheDocument();
  });

  it('ignores a response that arrives after the user cancels the optimized request', async () => {
    const off = deferred<CompileResponse>();
    const on = deferred<CompileResponse>();
    vi.mocked(compileCode).mockImplementationOnce(() => off.promise).mockImplementationOnce(() => on.promise);
    const user = userEvent.setup();

    renderCompare();
    await user.click(screen.getByRole('button', { name: '최적화 전후 비교하기' }));
    await act(async () => {
      off.resolve(result(0));
    });
    await waitFor(() => expect(compileCode).toHaveBeenCalledTimes(2));

    const [, requestOptions] = vi.mocked(compileCode).mock.calls[1];
    await user.click(screen.getByRole('button', { name: '대기 취소' }));
    expect(requestOptions?.signal?.aborted).toBe(true);

    await act(async () => {
      on.resolve(result(1));
    });
    await waitFor(() => expect(screen.getByRole('button', { name: '최적화 전후 비교하기' })).toBeEnabled());
    expect(screen.queryByText(/1개 → 1개/)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it.each([
    { changed: 'scope', nextScope: 'problem:two', nextOwner: 'account:alice' },
    { changed: 'owner', nextScope: 'problem:one', nextOwner: 'account:bob' },
  ])('aborts a pending request when the $changed changes', async ({ nextScope, nextOwner }) => {
    const off = deferred<CompileResponse>();
    const baseline = result(1);
    vi.mocked(compileCode).mockImplementationOnce(() => off.promise);
    const user = userEvent.setup();
    const view = renderCompare({ baseline });

    await user.click(screen.getByRole('button', { name: '최적화 전후 비교하기' }));
    const [, requestOptions] = vi.mocked(compileCode).mock.calls[0];

    act(() => {
      useCompilerStore.setState({ codeStorageScope: nextScope, codeStorageOwner: nextOwner });
    });
    view.rerender(
      <OptimizationCompare
        source={source}
        baseline={baseline}
        current
        scope={nextScope}
        owner={nextOwner}
      />,
    );

    await waitFor(() => expect(requestOptions?.signal?.aborted).toBe(true));
    expect(screen.getByRole('button', { name: '최적화 전후 비교하기' })).toBeEnabled();

    await act(async () => {
      off.resolve(result(0));
    });
    await waitFor(() => expect(compileCode).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/1개 → 1개/)).not.toBeInTheDocument();
  });
});
