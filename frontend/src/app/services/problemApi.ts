// 문제 관리 API

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

export const DIFFICULTY_LEVELS = [
  'iron5', 'iron4', 'iron3', 'iron2', 'iron1',
  'bronze5', 'bronze4', 'bronze3', 'bronze2', 'bronze1',
  'silver5', 'silver4', 'silver3', 'silver2', 'silver1',
  'gold5', 'gold4', 'gold3', 'gold2', 'gold1',
  'platinum5', 'platinum4', 'platinum3', 'platinum2', 'platinum1',
  'diamond5', 'diamond4', 'diamond3', 'diamond2', 'diamond1',
] as const;

export type ProblemDifficulty = (typeof DIFFICULTY_LEVELS)[number];

export type ProblemTag = 'io' | 'control' | 'func';

export interface Problem {
  id: string;
  title: string;
  difficulty: ProblemDifficulty;
  tags: ProblemTag[];
  description: string;
  testCases: TestCase[];
  hiddenTestCases: TestCase[];
  createdAt: string;
}

export type ProblemCreateRequest = Omit<Problem, 'id' | 'createdAt'>;

export interface SubmissionDetail {
  caseNumber: number;
  phase: 'sample' | 'hidden';
  isVisible: boolean;
  status: 'Correct' | 'Wrong' | 'Error';
  input: string;
  expected: string;
  actual: string;
}

export interface ProblemSubmissionResult {
  status: 'SampleFailed' | 'Rejected' | 'Accepted';
  totalCases: number;
  passedCases: number;
  sampleTotalCases: number;
  samplePassedCases: number;
  hiddenTotalCases: number;
  hiddenPassedCases: number;
  hiddenCompleted: boolean;
  totalScore: number;
  details: SubmissionDetail[];
}

export interface LeaderboardEntry {
  rank: number;
  username: string;
  totalScore: number;
  avatarUrl?: string | null;
}

export interface LeaderboardScoreRequest {
  username: string;
  points: number;
  challengeId: string;
  avatarUrl?: string | null;
}

export interface LeaderboardScoreResult extends LeaderboardEntry {
  challengeId: string;
  awardedPoints: number;
  alreadySolved: boolean;
}

// 문제 목록 조회
export async function getProblems(): Promise<Problem[]> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems/`);
  if (!res.ok) throw new Error('문제 목록을 불러오지 못했습니다.');
  return res.json();
}

// 문제 추가
export async function createProblem(data: ProblemCreateRequest): Promise<Problem> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems/`, {
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

export async function submitProblem(id: string, code: string, language: string): Promise<ProblemSubmissionResult> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (typeof window !== 'undefined') {
    const token = window.localStorage.getItem('authToken');
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const res = await fetch(`${API_BASE_URL}/api/v1/problems/${id}/submit`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ code, language }),
  });

  if (!res.ok) {
    const errorData = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail || '문제 제출에 실패했습니다.');
  }

  return res.json();
}

export async function getLeaderboard(limit = 50): Promise<LeaderboardEntry[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE_URL}/api/v1/problems/leaderboard?${params.toString()}`);
  if (!res.ok) throw new Error('리더보드를 불러오지 못했습니다.');
  return res.json();
}

export async function submitLeaderboardScore(data: LeaderboardScoreRequest): Promise<LeaderboardScoreResult> {
  const res = await fetch(`${API_BASE_URL}/api/v1/problems/leaderboard/score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('리더보드 점수 저장에 실패했습니다.');
  return res.json();
}
