import { create } from 'zustand';

export type OutputLine = {
  type: 'info' | 'success' | 'error' | 'input' | 'warning' | 'normal';
  text: string;
};

interface CompilerState {
  code: string;
  setCode: (code: string) => void;
  output: OutputLine[];
  addOutput: (line: OutputLine) => void;
  clearOutput: () => void;
  runCode: () => void;
  restartConsole: () => void;
  isRunning: boolean;
  isGraphViewerOpen: boolean;
  setGraphViewerOpen: (isOpen: boolean) => void;
  activeGraphTab: 'AST' | 'SSA' | 'IR' | 'ASM';
  setActiveGraphTab: (tab: 'AST' | 'SSA' | 'IR' | 'ASM') => void;
  selectedText: string;
  setSelectedText: (text: string) => void;
  theme: 'dark' | 'light';
  toggleTheme: () => void;
}

export const useCompilerStore = create<CompilerState>((set, get) => ({
  code: '',
  setCode: (code) => set({ code }),
  output: [
    { type: 'info', text: 'B++ 컴파일러 v1.0.0 초기화 중...' },
    { type: 'success', text: '컴파일러 환경이 준비되었습니다.' },
    { type: 'input', text: '> _' }
  ],
  addOutput: (line) => set((state) => ({ output: [...state.output, line] })),
  clearOutput: () => set({ output: [{ type: 'input', text: '> _' }] }),
  restartConsole: () => set({ 
    output: [
      { type: 'info', text: '컴파일러 환경 재시작 중...' },
      { type: 'success', text: '컴파일러 환경이 준비되었습니다.' },
      { type: 'input', text: '> _' }
    ] 
  }),
  isRunning: false,
  isGraphViewerOpen: true,
  setGraphViewerOpen: (isOpen) => set({ isGraphViewerOpen: isOpen }),
  activeGraphTab: 'AST',
  setActiveGraphTab: (tab) => set({ activeGraphTab: tab }),
  selectedText: '',
  setSelectedText: (text) => set({ selectedText: text }),
  theme: 'dark',
  toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
  runCode: () => {
    const { code, addOutput } = get();
    
    if (get().isRunning) return;
    set({ isRunning: true });
    
    // 기존 출력에 실행 로그 추가 (새로 지우기보다는 이어서 표시)
    const newOutput: OutputLine[] = [
      ...get().output.filter(o => o.type !== 'input'),
      { type: 'info', text: '\n> 컴파일 시작...' }
    ];
    set({ output: newOutput });

    setTimeout(() => {
      // 구문 에러 체크 (간단한 시뮬레이션: 세미콜론 누락 등)
      if (code.includes('main()') && !code.includes('{')) {
        addOutput({ type: 'error', text: 'SyntaxError: Expected "{" after main()' });
        addOutput({ type: 'info', text: '프로그램이 비정상 종료되었습니다. (코드: 1)' });
        addOutput({ type: 'input', text: '> _' });
        set({ isRunning: false });
        return;
      }

      addOutput({ type: 'success', text: '> 빌드 성공 (0ms)' });
      addOutput({ type: 'info', text: '> 프로그램 실행 중...' });

      setTimeout(() => {
        // 출력 시뮬레이션
        let outputText = '';
        
        // cout 추출 (여러 줄 지원)
        const coutRegex = /cout\s*<<\s*"([^"]*)"/g;
        let match;
        let hasOutput = false;
        
        while ((match = coutRegex.exec(code)) !== null) {
          outputText += match[1];
          hasOutput = true;
          // 간단하게 endl 처리
          if (code.substring(match.index).split(';')[0].includes('endl')) {
             outputText += '\n';
          }
        }

        if (hasOutput) {
          addOutput({ type: 'normal', text: outputText });
        } else {
          addOutput({ type: 'warning', text: '(출력된 내용이 없습니다)' });
        }

        addOutput({ type: 'info', text: '\n> 프로그램이 0 상태 코드로 종료되었습니다.' });
        addOutput({ type: 'input', text: '> _' });
        set({ isRunning: false });
      }, 600); // 실행 시간
      
    }, 400); // 빌드 시간
  }
}));
