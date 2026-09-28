import type { SourceSelectionRange } from '../store/compilerStore';

export type CompilerTutorialStep = {
  label: string;
  description: string;
  range: SourceSelectionRange;
};

export type CompilerTutorial = {
  id: 'branch' | 'loop' | 'function-call';
  title: string;
  summary: string;
  code: string;
  steps: CompilerTutorialStep[];
};

// Keep these examples deliberately small: each one is a complete B++ program that
// mirrors the current `func main() -> u64` template and the compiler reference tests.
export const BPP_COMPILER_TUTORIALS: CompilerTutorial[] = [
  {
    id: 'branch',
    title: '조건 분기',
    summary: '조건이 참일 때와 거짓일 때 서로 다른 return 경로를 확인합니다.',
    code: `func main() -> u64 {
    var score: u64 = 12;
    if (score > 10) {
        return 1;
    }
    return 0;
}
`,
    steps: [
      {
        label: '값 준비',
        description: 'score에 비교할 정수 값을 저장합니다.',
        range: { startLine: 2, startColumn: 5, endLine: 2, endColumn: 25 },
      },
      {
        label: '조건 평가',
        description: 'score가 10보다 큰지 검사해 두 경로 중 하나를 고릅니다.',
        range: { startLine: 3, startColumn: 5, endLine: 3, endColumn: 20 },
      },
      {
        label: '기본 경로',
        description: '조건이 거짓이면 마지막 return 0으로 이어집니다.',
        range: { startLine: 6, startColumn: 5, endLine: 6, endColumn: 14 },
      },
    ],
  },
  {
    id: 'loop',
    title: '반복문',
    summary: 'while 조건과 누적, 갱신이 반복되는 흐름을 살펴봅니다.',
    code: `func main() -> u64 {
    var index: u64 = 0;
    var total: u64 = 0;
    while (index < 4) {
        total = total + index;
        index = index + 1;
    }
    return total;
}
`,
    steps: [
      {
        label: '반복 조건',
        description: 'index가 4보다 작은 동안 본문을 다시 실행합니다.',
        range: { startLine: 4, startColumn: 5, endLine: 4, endColumn: 22 },
      },
      {
        label: '값 누적',
        description: '현재 index를 total에 더합니다.',
        range: { startLine: 5, startColumn: 9, endLine: 5, endColumn: 30 },
      },
      {
        label: '반복 갱신',
        description: '다음 반복을 위해 index를 하나 증가시킵니다.',
        range: { startLine: 6, startColumn: 9, endLine: 6, endColumn: 26 },
      },
    ],
  },
  {
    id: 'function-call',
    title: '함수 호출',
    summary: '별도 함수에 값을 전달하고 반환값을 다시 사용하는 과정을 봅니다.',
    code: `func increment(value: u64) -> u64 {
    return value + 1;
}

func main() -> u64 {
    var input: u64 = 4;
    var output: u64 = increment(input);
    return output;
}
`,
    steps: [
      {
        label: '함수 정의',
        description: 'increment는 u64 값을 받아 u64 값을 돌려줍니다.',
        range: { startLine: 1, startColumn: 1, endLine: 1, endColumn: 36 },
      },
      {
        label: '함수 호출',
        description: 'input을 increment에 전달하고 반환값을 output에 저장합니다.',
        range: { startLine: 7, startColumn: 23, endLine: 7, endColumn: 39 },
      },
      {
        label: '반환값 사용',
        description: 'main이 output을 최종 결과로 반환합니다.',
        range: { startLine: 8, startColumn: 5, endLine: 8, endColumn: 19 },
      },
    ],
  },
];

export function normalizeTutorialSource(source: string): string {
  return source.replace(/\r\n/g, '\n');
}

export function isTutorialSourceCurrent(source: string, tutorial: CompilerTutorial): boolean {
  return normalizeTutorialSource(source) === tutorial.code;
}
