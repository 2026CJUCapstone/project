// 문제 관리 API 서비스

function normalizeApiBaseUrl(value: string): string {
  if (!value || value === '/') return '';
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

const apiBaseFromBaseUrl = import.meta.env.BASE_URL === '/' ? '' : import.meta.env.BASE_URL.replace(/\/$/, '');
const API_BASE_URL = normalizeApiBaseUrl(import.meta.env.VITE_API_URL || apiBaseFromBaseUrl);

export interface TestCase {
  input: string;
  expectedOutput: string;
}

export type ProblemTag = 'io' | 'control' | 'func';

export interface Problem {
  id: string;
  title: string;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
  tags: ProblemTag[];
  description: string;
  testCases: TestCase[];
  createdAt: string;
}

export type ProblemCreateRequest = Omit<Problem, 'id' | 'createdAt'>;

// 문제 목록 조회
export async function getProblems(): Promise<Problem[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems`);
  if (!res.ok) throw new Error('문제 목록을 불러오지 못했습니다.');
  return res.json();
}

// 문제 추가
export async function createProblem(data: ProblemCreateRequest): Promise<Problem> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('문제 추가에 실패했습니다.');
  return res.json();
}

// 문제 삭제
export async function deleteProblem(id: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems/${id}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('문제 삭제에 실패했습니다.');
}

// 문제 수정
export async function updateProblem(id: string, data: ProblemCreateRequest): Promise<Problem> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('문제 수정에 실패했습니다.');
  return res.json();
}
