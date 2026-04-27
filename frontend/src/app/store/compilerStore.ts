import { create } from 'zustand';
import { checkHealth, compileCode, executeCode, type CompileResponse, type CompilerLanguage, type ExecuteResponse } from '../services/compilerApi';

export type OutputLine = {
  type: 'info' | 'success' | 'error' | 'input' | 'warning' | 'normal';
  text: string;
};

export type ConsoleTab = 'output' | 'terminal';
export type TerminalStatus = 'disconnected' | 'connecting' | 'connected';
export type TerminalLine = {
  type: 'system' | 'input' | 'output' | 'error';
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
  lastCompiledCode: string | null;
  compileAndRun: () => Promise<void>;
  compileAndStartTerminal: () => Promise<void>;
  compile: () => Promise<void>;
  activeConsoleTab: ConsoleTab;
  setActiveConsoleTab: (tab: ConsoleTab) => void;
  terminalStatus: TerminalStatus;
  terminalLines: TerminalLine[];
  clearTerminal: () => void;
  sendTerminalInput: (input: string) => void;
  // 자동저장 관련 상태
  lastSavedTime: number | null;
  autoSaveEnabled: boolean;
  setAutoSaveEnabled: (enabled: boolean) => void;
  saveCode: (code: string) => void;
  loadCode: () => string | null;
}

const STORAGE_KEY = 'b-compiler-editor-code';
let activeRunController: AbortController | null = null;
let activeTerminalSocket: WebSocket | null = null;
let terminalStopRequested = false;

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

function getTerminalWebSocketUrl(): string {
  const configuredWsUrl = import.meta.env.VITE_WS_URL;
  const baseFromRoute = import.meta.env.BASE_URL === '/' ? '' : import.meta.env.BASE_URL.replace(/\/$/, '');
  const baseValue = configuredWsUrl || import.meta.env.VITE_API_URL || baseFromRoute || window.location.origin;
  const url = new URL(baseValue, window.location.origin);

  url.protocol = url.protocol === 'https:' || url.protocol === 'wss:' ? 'wss:' : 'ws:';

  if (!url.pathname.endsWith('/ws/terminal')) {
    const path = url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '');
    url.pathname = `${path}/ws/terminal`;
  }

  url.search = '';
  url.hash = '';
  return url.toString();
}

function closeTerminalSocket() {
  const current = activeTerminalSocket;
  activeTerminalSocket = null;
  if (current && current.readyState !== WebSocket.CLOSED) {
    current.close();
  }
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
    const hadTerminalSession = Boolean(activeTerminalSocket);
    const hadHttpRun = Boolean(activeRunController);

    if (activeRunController) {
      activeRunController.abort();
      activeRunController = null;
    }

    if (activeTerminalSocket) {
      terminalStopRequested = true;
      closeTerminalSocket();
    }

    if (!hadTerminalSession && !hadHttpRun) {
      return;
    }

    set((state) => ({
      isRunning: false,
      lastError: '실행이 사용자에 의해 취소되었습니다.',
      terminalStatus: 'disconnected',
      terminalLines: hadTerminalSession
        ? [...state.terminalLines, { type: 'system', text: '실행이 중지되었습니다.' }]
        : state.terminalLines,
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
  activeConsoleTab: 'output',
  setActiveConsoleTab: (tab) => set({ activeConsoleTab: tab }),
  terminalStatus: 'disconnected',
  terminalLines: [],
  clearTerminal: () => set({ terminalLines: [] }),
  sendTerminalInput: (input) => {
    const socket = activeTerminalSocket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      set((state) => ({
        terminalLines: [...state.terminalLines, { type: 'error', text: '터미널이 실행 중이 아닙니다.' }],
      }));
      return;
    }

    socket.send(`${input}\n`);
    set((state) => ({
      terminalLines: [
        ...state.terminalLines,
        {
          type: 'input',
          text: input.length > 0 ? `stdin> ${input}` : 'stdin> <empty line>',
        },
      ],
    }));
  },
  selectedText: '',
  setSelectedText: (text) => set({ selectedText: text }),
  theme: 'dark',
  toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
  
  // 컴파일 관련 상태 및 함수
  isCompiling: false,
  lastCompile: null,
  lastCompiledCode: null,

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
        lastCompiledCode: code,
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

  compileAndStartTerminal: async () => {
    const { code, compile, isCompiling, isRunning, language } = get();
    if (isCompiling || isRunning) {
      return;
    }

    await compile();

    const { lastCompile, lastCompiledCode } = get();
    if (!lastCompile?.success || lastCompiledCode !== code) {
      return;
    }

    if (!code.trim()) {
      return;
    }

    if (activeTerminalSocket) {
      terminalStopRequested = true;
      closeTerminalSocket();
    }

    set((state) => ({
      activeConsoleTab: 'terminal',
      terminalStatus: 'connecting',
      terminalLines: [{ type: 'system', text: '프로그램 터미널 준비 중...' }],
      isRunning: true,
      backendStatus: 'checking',
      lastError: null,
      output: appendPrompt([
        ...state.output.filter((line) => line.type !== 'input'),
        { type: 'info', text: '> 터미널 세션을 시작하는 중...' },
      ]),
    }));

    try {
      await checkHealth();
      set({ backendStatus: 'online' });
    } catch (error) {
      const message = error instanceof Error ? error.message : '터미널 세션을 시작할 수 없습니다.';
      set((state) => ({
        isRunning: false,
        terminalStatus: 'disconnected',
        backendStatus: 'offline',
        lastError: message,
        terminalLines: [...state.terminalLines, { type: 'error', text: message }],
        output: appendPrompt([
          ...state.output.filter((line) => line.type !== 'input'),
          { type: 'error', text: `> ${message}` },
        ]),
      }));
      return;
    }

    await new Promise<void>((resolve) => {
      const socket = new WebSocket(getTerminalWebSocketUrl());
      let settled = false;

      const finish = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };

      terminalStopRequested = false;
      activeTerminalSocket = socket;

      socket.onopen = () => {
        if (activeTerminalSocket !== socket) {
          finish();
          return;
        }

        socket.send(JSON.stringify({ type: 'start', code, language, optimize: false }));
        set((state) => ({
          terminalStatus: 'connected',
          terminalLines: [...state.terminalLines, { type: 'system', text: `${language.toUpperCase()} 프로그램 stdin 연결됨` }],
          output: appendPrompt([
            ...state.output.filter((line) => line.type !== 'input'),
            { type: 'success', text: `> ${language.toUpperCase()} 실행 세션이 시작되었습니다.` },
          ]),
        }));
        finish();
      };

      socket.onmessage = (event) => {
        if (activeTerminalSocket !== socket) return;

        const chunk = String(event.data);
        const normalized = chunk.replace(/\r\n/g, '\n').trimEnd();

        set((state) => ({
          terminalLines: [...state.terminalLines, { type: 'output', text: chunk }],
          output: normalized
            ? [...state.output, { type: normalized.startsWith('>') ? 'info' : 'normal', text: normalized }]
            : state.output,
        }));
      };

      socket.onerror = () => {
        if (activeTerminalSocket !== socket) return;

        set((state) => ({
          lastError: '터미널 연결 오류가 발생했습니다.',
          terminalLines: [...state.terminalLines, { type: 'error', text: '터미널 연결 오류' }],
          output: appendPrompt([
            ...state.output.filter((line) => line.type !== 'input'),
            { type: 'error', text: '> 터미널 연결 오류' },
          ]),
        }));
      };

      socket.onclose = () => {
        if (activeTerminalSocket === socket) {
          activeTerminalSocket = null;
        }

        const stoppedByUser = terminalStopRequested;
        terminalStopRequested = false;

        set((state) => ({
          isRunning: false,
          terminalStatus: 'disconnected',
          terminalLines: stoppedByUser
            ? state.terminalLines
            : [...state.terminalLines, { type: 'system', text: '터미널 세션이 종료되었습니다.' }],
          output: stoppedByUser
            ? state.output
            : appendPrompt([
                ...state.output.filter((line) => line.type !== 'input'),
                { type: 'info', text: '> 터미널 세션이 종료되었습니다.' },
              ]),
        }));
        finish();
      };
    });
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
