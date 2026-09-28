import { useState } from 'react';
import type { SourceSelectionRange } from '../store/compilerStore';
import { BPP_COMPILER_TUTORIALS, isTutorialSourceCurrent } from '../services/compilerTutorials';

type CompilerTutorialProps = {
  onLoad: (code: string) => void;
  onSelect: (range: SourceSelectionRange) => void;
  currentSource: string;
  disabled: boolean;
  onCompile?: () => void;
};

const buttonClass = 'rounded border border-slate-300 px-2 py-1 text-xs font-medium transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-neutral-600 dark:hover:bg-neutral-800';

export function CompilerTutorial({ onLoad, onSelect, currentSource, disabled, onCompile }: CompilerTutorialProps) {
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState(BPP_COMPILER_TUTORIALS[0].id);
  const [stepIndex, setStepIndex] = useState(0);
  const selectedTutorial = BPP_COMPILER_TUTORIALS.find((tutorial) => tutorial.id === selectedId) ?? BPP_COMPILER_TUTORIALS[0];
  const sourceIsCurrent = isTutorialSourceCurrent(currentSource, selectedTutorial);
  const canNavigate = !disabled && sourceIsCurrent;
  const activeStep = selectedTutorial.steps[stepIndex];

  const chooseTutorial = (id: typeof selectedId) => {
    setSelectedId(id);
    setStepIndex(0);
  };

  const selectStep = (index: number) => {
    if (!canNavigate) return;
    setStepIndex(index);
    onSelect(selectedTutorial.steps[index].range);
  };

  return (
    <section aria-label="B++ 예제 따라하기" className="border-b border-slate-200 text-xs dark:border-neutral-700">
      <button
        type="button"
        aria-controls="compiler-tutorial-panel"
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left font-semibold hover:bg-slate-50 dark:hover:bg-neutral-900"
        onClick={() => setOpen((value) => !value)}
      >
        <span>B++ 예제 따라하기</span>
        <span aria-hidden="true">{open ? '접기' : '펼치기'}</span>
      </button>

      {open && <div id="compiler-tutorial-panel" className="space-y-3 px-3 pb-3">
        <p className="text-slate-500 dark:text-neutral-400">예제를 불러오고 컴파일한 뒤 단계를 누르면 코드와 그래프가 함께 강조됩니다. 코드를 바꾸면 다시 컴파일하세요.</p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="B++ 예제 선택">
          {BPP_COMPILER_TUTORIALS.map((tutorial) => <button
            key={tutorial.id}
            type="button"
            aria-pressed={tutorial.id === selectedTutorial.id}
            className={buttonClass}
            disabled={disabled}
            onClick={() => chooseTutorial(tutorial.id)}
          >{tutorial.title}</button>)}
        </div>

        <div className="rounded border border-slate-200 p-2 dark:border-neutral-700">
          <p className="font-semibold">{selectedTutorial.title}</p>
          <p className="mt-1 text-slate-500 dark:text-neutral-400">{selectedTutorial.summary}</p>
          <pre aria-label={`${selectedTutorial.title} 예제 코드`} className="mt-2 max-h-36 overflow-auto rounded bg-slate-950 p-2 text-[11px] leading-4 text-slate-100">{selectedTutorial.code}</pre>
          <button type="button" className={`${buttonClass} mt-2`} disabled={disabled} onClick={() => onLoad(selectedTutorial.code)}>예제 불러오기</button>
          {onCompile && <button type="button" className={`${buttonClass} ml-2 mt-2`} disabled={!canNavigate} onClick={onCompile}>예제 컴파일</button>}
        </div>

        {!sourceIsCurrent && <p role="status" className="text-slate-500 dark:text-neutral-400">예제를 불러온 뒤 코드가 그대로일 때 단계별 위치로 이동할 수 있습니다.</p>}
        <div aria-label="학습 단계" className="space-y-2">
          <p className="font-medium">{stepIndex + 1}. {activeStep.label}</p>
          <p className="text-slate-500 dark:text-neutral-400">{activeStep.description}</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonClass} disabled={!canNavigate || stepIndex === 0} onClick={() => selectStep(stepIndex - 1)}>이전 단계</button>
            <button type="button" className={buttonClass} disabled={!canNavigate || stepIndex === selectedTutorial.steps.length - 1} onClick={() => selectStep(stepIndex + 1)}>다음 단계</button>
            {selectedTutorial.steps.map((step, index) => <button
              key={step.label}
              type="button"
              aria-current={index === stepIndex ? 'step' : undefined}
              className={buttonClass}
              disabled={!canNavigate}
              onClick={() => selectStep(index)}
            >{index + 1}. {step.label}</button>)}
          </div>
        </div>
      </div>}
    </section>
  );
}
