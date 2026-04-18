import { create } from 'zustand';
import { checkHealth, compileCode, executeCode, type CompileResponse, type CompilerLanguage, type ExecuteResponse } from '../services/compilerApi';

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
  runCode: () => Promise<void>;
  cancelRun: () => void;
  restartConsole: () => void;
  isRunning: boolean;
  backendStatus: 'idle' | 'checking' | 'online' | 'offline';
  lastExecution: ExecuteResponse | null;
  lastError: string | null;
  language: CompilerLanguage;
  setLanguage: (language: CompilerLanguage) => void;
  isGraphViewerOpen: boolean;
  setGraphViewerOpen: (isOpen: boolean) => void;
  activeGraphTab: 'AST' | 'SSA' | 'IR' | 'ASM';
  setActiveGraphTab: (tab: 'AST' | 'SSA' | 'IR' | 'ASM') => void;
  selectedText: string;
  setSelectedText: (text: string) => void;
  theme: 'dark' | 'light';
  toggleTheme: () => void;
  // 컴파일 관련 상태
  isCompiling: boolean;
  lastCompile: CompileResponse | null;
  compileAndRun: () => Promise<void>;
  compile: () => Promise<void>;
  // 자동저장 관련 상태
  lastSavedTime: number | null;
  autoSaveEnabled: boolean;
  setAutoSaveEnabled: (enabled: boolean) => void;
  saveCode: (code: string) => void;
  loadCode: () => string | null;
}

const STORAGE_KEY = 'b-compiler-editor-code';
let activeRunController: AbortController | null = null;

const INITIAL_OUTPUT: OutputLine[] = [
  { type: 'info', text: 'B++ 컴파일러 v1.0.0 초기화 중...' },
  { type: 'success', text: '컴파일러 환경이 준비되었습니다.' },
];

function formatExecutionTime(milliseconds: number): string {
  if (milliseconds >= 1000) {
    return `${(milliseconds / 1000).toFixed(2)}s`;
  }
  return `${Math.round(milliseconds)}ms`;
}

function appendPrompt(lines: OutputLine[]): OutputLine[] {
  return lines;
}

export const useCompilerStore = create<CompilerState>((set, get) => ({
  code: '',
  setCode: (code) => set({ code }),
  output: INITIAL_OUTPUT,
  addOutput: (line) => set((state) => ({ output: [...state.output, line] })),
  clearOutput: () => set({ output: [] }),
  restartConsole: () => set({ 
    output: [
      { type: 'info', text: '컴파일러 환경 재시작 중...' },
      { type: 'success', text: '컴파일러 환경이 준비되었습니다.' },
    ],
    lastError: null,
  }),
  isRunning: false,
  cancelRun: () => {
    if (activeRunController) {
      activeRunController.abort();
      activeRunController = null;
    }

    set((state) => ({
      isRunning: false,
      lastError: '실행이 사용자에 의해 취소되었습니다.',
      output: appendPrompt([
        ...state.output.filter((line) => line.type !== 'input'),
        { type: 'warning', text: '> 실행이 취소되었습니다.' },
      ]),
    }));
  },
  backendStatus: 'idle',
  lastExecution: null,
  lastError: null,
  language: 'bpp',
  setLanguage: (language) => set({ language }),
  isGraphViewerOpen: true,
  setGraphViewerOpen: (isOpen) => set({ isGraphViewerOpen: isOpen }),
  activeGraphTab: 'AST',
  setActiveGraphTab: (tab) => set({ activeGraphTab: tab }),
  selectedText: '',
  setSelectedText: (text) => set({ selectedText: text }),
  theme: 'dark',
  toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
  
  // 컴파일 관련 상태 및 함수
  isCompiling: false,
  lastCompile: null,

  compile: async () => {
    const { code, isCompiling, language } = get();
    if (isCompiling) return;

    if (!code.trim()) {
      set((state) => ({
        output: appendPrompt([
          ...state.output.filter((line) => line.type !== 'input'),
          { type: 'warning', text: '> 컴파일할 코드가 없습니다.' },
        ]),
      }));
      return;
    }

    set((state) => ({
      isCompiling: true,
      lastError: null,
      output: [
        ...state.output.filter((line) => line.type !== 'input'),
        { type: 'info', text: '> 코드 컴파일 중...' },
      ],
    }));

    try {
      const result = await compileCode({
        code,
        language,
        options: { optimize: false, target: 'all' },
      });

      const nextOutput: OutputLine[] = [
        ...get().output.filter((line) => line.type !== 'input'),
      ];

      if (result.success) {
        nextOutput.push({ type: 'success', text: `> 컴파일 성공 (${formatExecutionTime(result.executionTime)})` });
      } else {
        nextOutput.push({ type: 'error', text: `> 컴파일 실패 (${formatExecutionTime(result.executionTime)})` });
      }

      if (result.errors?.length) {
        for (const err of result.errors) {
          nextOutput.push({
            type: 'error',
            text: `  [${err.severity}] Line ${err.line}:${err.column} — ${err.message}`,
          });
        }
      }

      if (result.warnings?.length) {
        for (const warn of result.warnings) {
          nextOutput.push({
            type: 'warning',
            text: `  [warning] Line ${warn.line}:${warn.column} — ${warn.message}`,
          });
        }
      }

      set({
        isCompiling: false,
        lastCompile: result,
        lastError: result.success ? null : '컴파일 오류가 발생했습니다.',
        output: appendPrompt(nextOutput),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : '컴파일 중 알 수 없는 오류가 발생했습니다.';
      set((state) => ({
        isCompiling: false,
        lastError: message,
        output: appendPrompt([
          ...state.output.filter((line) => line.type !== 'input'),
          { type: 'error', text: `> ${message}` },
        ]),
      }));
    }
  },

  compileAndRun: async () => {
    const { compile, runCode } = get();
    await compile();
    const { lastCompile } = get();
    if (lastCompile?.success) {
      await runCode();
    }
  },

  // 자동저장 관련 상태 및 함수
  lastSavedTime: null,
  autoSaveEnabled: true,
  setAutoSaveEnabled: (enabled) => set({ autoSaveEnabled: enabled }),
  
  saveCode: (code) => {
    try {
      localStorage.setItem(STORAGE_KEY, code);
      set({ lastSavedTime: Date.now() });
    } catch (error) {
      console.error('코드 저장 실패:', error);
    }
  },
  
  loadCode: () => {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (error) {
      console.error('코드 불러오기 실패:', error);
      return null;
    }
  },
  
  runCode: async () => {
    const { code, language, isRunning } = get();

    if (isRunning) {
      return;
    }

    if (!code.trim()) {
      set((state) => ({
        output: appendPrompt([
          ...state.output.filter((line) => line.type !== 'input'),
          { type: 'warning', text: '> 실행할 코드가 없습니다.' },
        ]),
      }));
      return;
    }

    activeRunController = new AbortController();

    set((state) => ({
      isRunning: true,
      backendStatus: 'checking',
      lastError: null,
      output: [
        ...state.output.filter((line) => line.type !== 'input'),
        { type: 'info', text: '> 백엔드 연결 확인 중...' },
        { type: 'info', text: `> ${language.toUpperCase()} 코드 실행 요청 중...` },
      ],
    }));

    try {
      await checkHealth();
      set({ backendStatus: 'online' });

      const result = await executeCode(
        {
          code,
          language,
        },
        { signal: activeRunController.signal },
      );

      activeRunController = null;

      const nextOutput: OutputLine[] = [
        ...get().output.filter((line) => line.type !== 'input'),
        {
          type: result.success ? 'success' : 'error',
          text: `> 실행 완료 (${formatExecutionTime(result.executionTime)}, exit code ${result.exitCode})`,
        },
      ];

      if (result.stdout.trim()) {
        nextOutput.push({ type: 'normal', text: result.stdout.trimEnd() });
      }

      if (result.stderr.trim()) {
        nextOutput.push({ type: result.success ? 'warning' : 'error', text: result.stderr.trimEnd() });
      }

      if (!result.stdout.trim() && !result.stderr.trim()) {
        nextOutput.push({ type: 'warning', text: '(출력된 내용이 없습니다)' });
      }

      set({
        isRunning: false,
        lastExecution: result,
        lastError: result.success ? null : result.stderr || `프로그램이 ${result.exitCode} 코드로 종료되었습니다.`,
        output: appendPrompt(nextOutput),
      });
    } catch (error) {
      activeRunController = null;
      const message = error instanceof Error ? error.message : '실행 중 알 수 없는 오류가 발생했습니다.';

      set((state) => ({
        isRunning: false,
        backendStatus: message.includes('백엔드') ? 'offline' : state.backendStatus,
        lastError: message,
        output: appendPrompt([
          ...state.output.filter((line) => line.type !== 'input'),
          { type: 'error', text: `> ${message}` },
        ]),
      }));
    }
  },
}));
