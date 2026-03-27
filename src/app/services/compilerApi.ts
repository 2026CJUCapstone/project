// API 기본 설정 및 타입 정의

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_TIMEOUT = parseInt(import.meta.env.VITE_API_TIMEOUT || '10000');

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

// ==================== API 호출 함수 ====================

/**
 * 코드 컴파일 및 중간 표현 생성
 */
export async function compileCode(request: CompileRequest): Promise<CompileResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE_URL}/api/compile`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
    }

    return await response.json();
  } catch (error: any) {
    if (error.name === 'AbortError') {
      throw new Error('컴파일 요청이 타임아웃되었습니다.');
    }
    throw new Error(`컴파일 API 오류: ${error.message}`);
  }
}

/**
 * 코드 실행
 */
export async function executeCode(request: ExecuteRequest): Promise<ExecuteResponse> {
  const controller = new AbortController();
  const timeout = request.timeout || API_TIMEOUT;
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(`${API_BASE_URL}/api/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
    }

    return await response.json();
  } catch (error: any) {
    if (error.name === 'AbortError') {
      throw new Error('코드 실행이 타임아웃되었습니다.');
    }
    throw new Error(`실행 API 오류: ${error.message}`);
  }
}

/**
 * 선택된 코드 영역 분석
 */
export async function analyzeSelection(request: AnalyzeSelectionRequest): Promise<AnalyzeSelectionResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE_URL}/api/analyze-selection`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.message || `HTTP ${response.status}: ${response.statusText}`);
    }

    return await response.json();
  } catch (error: any) {
    if (error.name === 'AbortError') {
      throw new Error('분석 요청이 타임아웃되었습니다.');
    }
    throw new Error(`분석 API 오류: ${error.message}`);
  }
}

/**
 * 백엔드 헬스 체크
 */
export async function checkHealth(): Promise<{ status: string; version?: string }> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      method: 'GET',
    });

    if (!response.ok) {
      throw new Error('Backend is not healthy');
    }

    return await response.json();
  } catch (error) {
    throw new Error('백엔드 서버에 연결할 수 없습니다.');
  }
}
