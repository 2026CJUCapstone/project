import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { SSAGraph, SourceRange } from '../services/compilerApi';
import { buildValueFlow } from '../services/valueFlow';
import { ValueFlowExplorer } from './ValueFlowExplorer';

const definitionRange: SourceRange = { startLine: 2, startColumn: 5, endLine: 2, endColumn: 20 };
const useRange: SourceRange = { startLine: 3, startColumn: 5, endLine: 3, endColumn: 15 };

const flowGraph: SSAGraph = {
  blocks: [
    {
      id: 'alpha:entry',
      functionId: 'alpha',
      label: 'alpha entry',
      instructions: ['r1 = const 1', 'return r1'],
      instructionSourceRanges: [[definitionRange], [useRange]],
      instructionDetails: [
        { id: 'alpha-define', opcode: 'const', result: 'r1', uses: [], complete: true },
        { id: 'alpha-use', opcode: 'return', uses: ['r1'], complete: true },
      ],
      predecessors: [],
      successors: [],
    },
    {
      id: 'beta:entry',
      functionId: 'beta',
      label: 'beta entry',
      instructions: ['r1 = const 2'],
      instructionSourceRanges: [[definitionRange]],
      instructionDetails: [{ id: 'beta-define', opcode: 'const', result: 'r1', uses: [], complete: true }],
      predecessors: [],
      successors: [],
    },
  ],
  edges: [],
};

function renderExplorer(graph = flowGraph, selected = undefined) {
  const onSelect = vi.fn();
  const navigate = vi.fn();
  const view = render(<ValueFlowExplorer graph={graph} selected={selected} onSelect={onSelect} navigate={navigate} />);
  return { onSelect, navigate, ...view };
}

describe('ValueFlowExplorer', () => {
  it('keeps equal SSA names isolated by function while searching, selecting, and navigating locations', async () => {
    const user = userEvent.setup();
    const { onSelect, navigate, rerender } = renderExplorer();

    expect(screen.getByRole('button', { name: 'alpha · r1' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'beta · r1' })).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'SSA 값 검색' }), 'alpha');
    expect(screen.getByRole('button', { name: 'alpha · r1' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'beta · r1' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'alpha · r1' }));
    expect(onSelect).toHaveBeenCalledWith('alpha', 'r1');

    const alphaR1 = buildValueFlow(flowGraph).find((entry) => entry.functionId === 'alpha' && entry.label === 'r1');
    rerender(<ValueFlowExplorer graph={flowGraph} selected={alphaR1} onSelect={onSelect} navigate={navigate} />);
    expect(screen.getByText('alpha · r1 — 정의 1곳 / 사용 1곳')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '정의 · alpha entry · 1번 명령' }));
    await user.click(screen.getByRole('button', { name: '사용 · alpha entry · 2번 명령' }));
    expect(navigate).toHaveBeenNthCalledWith(1, definitionRange);
    expect(navigate).toHaveBeenNthCalledWith(2, useRange);
  });

  it('warns when structured value evidence is absent or incomplete', () => {
    const noData: SSAGraph = {
      blocks: [{ id: 'main:entry', label: 'main entry', instructions: ['r1 = add r2, r3'], predecessors: [], successors: [] }],
      edges: [],
    };
    const { unmount } = renderExplorer(noData);
    expect(screen.getByRole('status')).toHaveTextContent('이 결과에는 구조화된 값 정보가 없습니다. 새 컴파일러로 다시 컴파일해야 합니다.');
    unmount();

    renderExplorer({
      blocks: [{
        id: 'main:entry',
        label: 'main entry',
        instructions: ['r1 = unknown'],
        instructionDetails: [{ id: 'partial', opcode: 'unknown', result: 'r1', uses: [], complete: false }],
        predecessors: [],
        successors: [],
      }],
      edges: [],
    });
    expect(screen.getByText('일부 명령의 사용 정보가 불완전합니다. 표시된 연결만 확인할 수 있습니다.')).toBeInTheDocument();
  });

  it('disables stale source navigation while retaining the compiled value evidence', async () => {
    const navigate = vi.fn();
    const selected = buildValueFlow(flowGraph)[0];
    render(<ValueFlowExplorer graph={flowGraph} selected={selected} onSelect={vi.fn()} navigate={navigate} canNavigate={false} />);
    const definition = screen.getByRole('button', { name: '정의 · alpha entry · 1번 명령' });
    expect(definition).toBeDisabled();
    await userEvent.click(definition);
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByText('alpha · r1 — 정의 1곳 / 사용 1곳')).toBeVisible();
  });
});
