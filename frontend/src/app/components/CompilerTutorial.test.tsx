import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CompilerTutorial } from './CompilerTutorial';
import { BPP_COMPILER_TUTORIALS } from '../services/compilerTutorials';

const branch = BPP_COMPILER_TUTORIALS[0];
const loop = BPP_COMPILER_TUTORIALS[1];

function renderTutorial(currentSource = 'func main() -> u64 {\n    return 0;\n}\n') {
  const onLoad = vi.fn();
  const onSelect = vi.fn();
  const view = render(<CompilerTutorial currentSource={currentSource} onLoad={onLoad} onSelect={onSelect} disabled={false} />);
  return { onLoad, onSelect, ...view };
}

describe('CompilerTutorial', () => {
  it('does not replace code when the tutorial is opened or another example is selected', async () => {
    const user = userEvent.setup();
    const { onLoad } = renderTutorial();

    await user.click(screen.getByRole('button', { name: 'B++ 예제 따라하기' }));
    await user.click(screen.getByRole('button', { name: '반복문' }));

    expect(screen.getByLabelText('반복문 예제 코드').textContent).toBe(loop.code);
    expect(onLoad).not.toHaveBeenCalled();
  });

  it('loads only the explicitly selected example', async () => {
    const user = userEvent.setup();
    const { onLoad } = renderTutorial();

    await user.click(screen.getByRole('button', { name: 'B++ 예제 따라하기' }));
    await user.click(screen.getByRole('button', { name: '함수 호출' }));
    await user.click(screen.getByRole('button', { name: '예제 불러오기' }));

    expect(onLoad).toHaveBeenCalledTimes(1);
    expect(onLoad).toHaveBeenCalledWith(BPP_COMPILER_TUTORIALS[2].code);
  });

  it('selects the exact instructional range only while the selected source is current', async () => {
    const user = userEvent.setup();
    const { onSelect, rerender } = renderTutorial(branch.code.replace(/\n/g, '\r\n'));

    await user.click(screen.getByRole('button', { name: 'B++ 예제 따라하기' }));
    await user.click(screen.getByRole('button', { name: '2. 조건 평가' }));
    expect(onSelect).toHaveBeenCalledWith(branch.steps[1].range);

    rerender(<CompilerTutorial currentSource={`${branch.code}// changed\n`} onLoad={vi.fn()} onSelect={onSelect} disabled={false} />);
    expect(screen.getByRole('button', { name: '3. 기본 경로' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: '3. 기본 경로' }));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('prevents loading and source navigation while disabled', async () => {
    const user = userEvent.setup();
    const onLoad = vi.fn();
    const onSelect = vi.fn();
    render(<CompilerTutorial currentSource={branch.code} onLoad={onLoad} onSelect={onSelect} disabled />);

    await user.click(screen.getByRole('button', { name: 'B++ 예제 따라하기' }));
    expect(screen.getByRole('button', { name: '예제 불러오기' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '1. 값 준비' })).toBeDisabled();
    expect(onLoad).not.toHaveBeenCalled();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
