import { API_BASE_URL, getAuthHeaders } from './apiBase';
import type { CompilerLanguage } from './compilerApi';

export type ContestState = 'draft' | 'upcoming' | 'running' | 'finalizing' | 'finished';
export interface ContestProblem { id: string; problemId: string; label: string; title: string; points: number; difficulty: string }
export interface Contest {
  id: string; title: string; description: string; startsAt: string; endsAt: string; serverTime: string;
  state: ContestState; published: boolean; joined: boolean; canManage: boolean; participantCount: number; problems: ContestProblem[];
}
export interface ContestProblemDetail extends ContestProblem {
  description: string; tags: string[]; testCases: { input: string; expectedOutput: string }[]; contest: Contest;
}
export interface ContestSubmission {
  id: string; contestProblemId: string; language: CompilerLanguage; receivedAt: string;
  status: 'queued' | 'running' | 'completed'; verdict: string; finishedAt: string | null; code?: string;
}
export interface Scoreboard {
  state: ContestState; serverTime: string; pendingCount: number;
  problems: { id: string; label: string; points: number }[];
  rows: { rank: number; userId: string; username: string; totalPoints: number; penaltySeconds: number;
    problems: { contestProblemId: string; label: string; points: number; wrongAttempts: number; elapsedSeconds: number | null; pending: boolean; verdict: string | null }[] }[];
}
export interface NewContestProblem {
  title: string; description: string; difficulty: string; tags: string[]; points: number;
  testCases: { input: string; expectedOutput: string }[];
  hiddenTestCases: { input: string; expectedOutput: string }[];
}
export interface ContestWrite {
  title: string; description: string; startsAt: string; endsAt: string; published: boolean;
  problems: { problemId?: string; points: number; newProblem?: NewContestProblem | null }[];
}
export async function contestRequest<T>(path = '', method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api/v1/contests${path}`, {
    method, signal, headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '요청을 처리하지 못했습니다. 입력값을 확인하세요.');
  }
  return response.json();
}
export async function contestPageRequest<T>(path = '', limit = 50, offset = 0, signal?: AbortSignal,
  filters: { state?: string; search?: string } = {}): Promise<{ items: T[]; total: number }> {
  const separator = path.includes('?') ? '&' : '?';
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (filters.state && filters.state !== 'all') params.set('state', filters.state);
  if (filters.search?.trim()) params.set('search', filters.search.trim());
  const response = await fetch(`${API_BASE_URL}/api/v1/contests${path}${separator}${params}`, {
    signal, headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : '목록을 불러오지 못했습니다.');
  }
  const items = await response.json() as T[];
  return { items, total: Number(response.headers.get('X-Total-Count') ?? items.length) };
}
export const CONTEST_STATES: Record<ContestState, string> = {
  draft: '초안', upcoming: '예정', running: '진행 중', finalizing: '최종 채점 중', finished: '종료',
};
export const VERDICTS: Record<string, string> = {
  pending: '대기', running: '채점 중', accepted: '정답', wrong_answer: '오답', compile_error: '컴파일 오류',
  runtime_error: '런타임 오류', time_limit_exceeded: '시간 초과', memory_limit_exceeded: '메모리 초과', system_error: '시스템 오류',
};
export function contestDate(date: string) {
  return new Date(date).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
}
export function duration(seconds: number) {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 3600).toString().padStart(2, '0')}:${Math.floor(value / 60 % 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`;
}
