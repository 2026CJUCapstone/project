// API 기본 설정 및 타입 정의

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_TIMEOUT = parseInt(import.meta.env.VITE_API_TIMEOUT || '10000', 10);

export type CompilerLanguage = 'python' | 'c' | 'cpp' | 'java' | 'javascript';

interface RequestOptions {
  signal?: AbortSignal;
  timeout?: number;
}

interface BackendErrorResponse {
  detail?: string;
  message?: string;
}

interface BackendRunResponse {
  stdout: string;
  stderr: string;
  exit_code: number;
  execution_time: number;
}

// ==================== 타입 정의 ====================

export interface ASTNode {
  id: string;
  type: string;
  label: string;
  children: string[];
  sourceLocation?: {
    line: number;
    column: number;
    endLine: number;
    endColumn: number;
  };
  metadata?: Record<string, any>;
}

export interface ASTGraph {
  nodes: ASTNode[];
  edges: {
    from: string;
    to: string;
    label?: string;
    type?: string;
  }[];
}

export interface SSABlock {
  id: string;
  label: string;
  instructions: string[];
  predecessors: string[];
  successors: string[];
}

export interface SSAGraph {
  blocks: SSABlock[];
  edges: {
    from: string;
    to: string;
    label?: string;
    type: 'true' | 'false' | 'unconditional';
  }[];
}

export interface IRInstruction {
  id: string;
  opcode: string;
  operands: string[];
  result?: string;
  comment?: string;
}

export interface ASMLine {
  address: string;
  label?: string;
  instruction: string;
  operands: string[];
  comment?: string;
}

export interface CompileError {
  line: number;
  column: number;
  message: string;
  severity: 'error' | 'warning' | 'info';
  code?: string;
}

export interface CompileRequest {
  code: string;
  options?: {
    optimize: boolean;
    target: 'ast' | 'ssa' | 'ir' | 'asm' | 'all';
    debug?: boolean;
  };
}

export interface CompileResponse {
  success: boolean;
  ast?: ASTGraph;
  ssa?: SSAGraph;
  ir?: {
    instructions: IRInstruction[];
  };
  asm?: {
    lines: ASMLine[];
  };
  errors?: CompileError[];
  warnings?: CompileError[];
  executionTime: number; // ms
  metadata?: {
    nodeCount?: number;
    optimizationLevel?: number;
  };
}

export interface ExecuteRequest {
  code: string;
  language?: CompilerLanguage;
  input?: string;
  timeout?: number; // ms
}

export interface ExecuteResponse {
  success: boolean;
  stdout: string;
  stderr: string;
  exitCode: number;
  executionTime: number; // ms
  memoryUsed?: number; // bytes
  cpuTime?: number; // ms
}

export interface AnalyzeSelectionRequest {
  code: string;
  selection: {
    startLine: number;
    endLine: number;
    startColumn?: number;
    endColumn?: number;
  };
}

export interface AnalyzeSelectionResponse {
  success: boolean;
  relatedNodes: string[]; // AST 노드 ID들
  affectedBlocks?: string[]; // SSA 블록 ID들
}

async function requestJson<T>(path: string, init: RequestInit, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), options.timeout ?? API_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: options.signal ?? controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      const errorData = (await response.json().catch(() => ({}))) as BackendErrorResponse;
      throw new Error(errorData.detail || errorData.message || `HTTP ${response.status}: ${response.statusText}`);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('요청이 취소되었거나 시간 초과되었습니다.');
    }

    throw error instanceof Error ? error : new Error('알 수 없는 API 오류가 발생했습니다.');
  } finally {
    clearTimeout(timeoutId);
  }
}

// ==================== API 호출 함수 ====================

/**
 * 코드 컴파일 및 중간 표현 생성
 */
export async function compileCode(request: CompileRequest, options: RequestOptions = {}): Promise<CompileResponse> {
  const response = await executeCode(
    {
      code: request.code,
      language: 'cpp',
      timeout: options.timeout,
    },
    options,
  );

  return {
    success: response.success,
    errors: response.stderr
      ? [
          {
            line: 0,
            column: 0,
            message: response.stderr,
            severity: response.exitCode === 0 ? 'warning' : 'error',
          },
        ]
      : [],
    executionTime: response.executionTime,
  };
}

/**
 * 코드 실행
 */
export async function executeCode(request: ExecuteRequest, options: RequestOptions = {}): Promise<ExecuteResponse> {
  const response = await requestJson<BackendRunResponse>(
    '/api/v1/compiler/run',
    {
      method: 'POST',
      body: JSON.stringify({
        language: request.language ?? 'cpp',
        source_code: request.code,
        stdin: request.input,
      }),
    },
    {
      ...options,
      timeout: request.timeout ?? options.timeout,
    },
  );

  return {
    success: response.exit_code === 0,
    stdout: response.stdout,
    stderr: response.stderr,
    exitCode: response.exit_code,
    executionTime: response.execution_time,
  };
}

/**
 * 선택된 코드 영역 분석
 */
export async function analyzeSelection(_request: AnalyzeSelectionRequest): Promise<AnalyzeSelectionResponse> {
  throw new Error('선택 영역 분석 API는 아직 백엔드에 구현되지 않았습니다.');
}

/**
 * 백엔드 헬스 체크
 */
export async function checkHealth(): Promise<{ status: string; version?: string }> {
  try {
    return await requestJson<{ status: string; version?: string }>(
      '/health',
      {
        method: 'GET',
        headers: {},
      },
      { timeout: 3000 },
    );
  } catch (_error) {
    throw new Error('백엔드 서버에 연결할 수 없습니다.');
  }
}
