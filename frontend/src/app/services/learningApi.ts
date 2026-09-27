import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';

export interface LearningTrack {
  id: string;
  title: string;
  description: string;
  order: number;
  total: number;
  solved: number;
  nextProblemId: string | null;
}

export interface LearningProblem {
  id: string;
  title: string;
  difficulty: string;
  tags: string[];
  solved: boolean;
  attempted: boolean;
  bookmarked: boolean;
  note: string;
  reviewedAt: string | null;
  lastAttemptAt: string | null;
  reason?: string;
}

export type LearningReviewFilter = 'unresolved' | 'bookmarked' | 'notes' | 'all';

export interface LearningTracksResponse {
  tracks: LearningTrack[];
  signedIn: boolean;
}

export interface LearningTrackPage {
  track: LearningTrack;
  items: LearningProblem[];
  total: number;
  offset: number;
  limit: number;
}

export interface LearningProblemPage {
  items: LearningProblem[];
  total: number;
  offset: number;
  limit: number;
}

export interface LearningRecommendationsResponse {
  items: LearningProblem[];
  targetDifficulty: string;
  signedIn: boolean;
}

export interface LearningProblemReview {
  problemId: string;
  bookmarked: boolean;
  note: string;
  reviewedAt: string | null;
  reviewed?: boolean;
  version: number;
}

export interface UpdateLearningProblemReviewRequest {
  bookmarked: boolean;
  note: string;
  reviewed: boolean;
  version: number;
}

const LEARNING_API_PATH = `${API_BASE_URL}/api/v1/learning`;

function pageQuery(limit: number, offset: number): URLSearchParams {
  return new URLSearchParams({ limit: String(limit), offset: String(offset) });
}

function normaliseReview(record: Omit<LearningProblemReview, 'version'> & { version?: number }): LearningProblemReview {
  return { ...record, version: record.version ?? 0 };
}

export async function getLearningTracks(signal?: AbortSignal): Promise<LearningTracksResponse> {
  const response = await fetch(`${LEARNING_API_PATH}/tracks`, { headers: getAuthHeaders(), signal });
  if (!response.ok) throw await parseApiError(response, '문제집을 불러오지 못했습니다.');
  return await response.json() as LearningTracksResponse;
}

export async function getLearningTrack(
  trackId: string,
  limit = 24,
  offset = 0,
  signal?: AbortSignal,
): Promise<LearningTrackPage> {
  const response = await fetch(
    `${LEARNING_API_PATH}/tracks/${encodeURIComponent(trackId)}?${pageQuery(limit, offset).toString()}`,
    { headers: getAuthHeaders(), signal },
  );
  if (!response.ok) throw await parseApiError(response, '문제집 문제를 불러오지 못했습니다.');
  return await response.json() as LearningTrackPage;
}

export async function getLearningReview(
  filter: LearningReviewFilter,
  limit = 24,
  offset = 0,
  signal?: AbortSignal,
): Promise<LearningProblemPage> {
  const query = pageQuery(limit, offset);
  query.set('filter', filter);
  const response = await fetch(`${LEARNING_API_PATH}/review?${query.toString()}`, {
    headers: getAuthHeaders(), signal,
  });
  if (!response.ok) throw await parseApiError(response, '복습 목록을 불러오지 못했습니다.');
  return await response.json() as LearningProblemPage;
}

export async function getLearningRecommendations(signal?: AbortSignal): Promise<LearningRecommendationsResponse> {
  const response = await fetch(`${LEARNING_API_PATH}/recommendations`, {
    headers: getAuthHeaders(), signal,
  });
  if (!response.ok) throw await parseApiError(response, '추천 문제를 불러오지 못했습니다.');
  return await response.json() as LearningRecommendationsResponse;
}

export async function getLearningProblemReview(
  problemId: string,
  signal?: AbortSignal,
): Promise<LearningProblemReview> {
  const response = await fetch(`${LEARNING_API_PATH}/problems/${encodeURIComponent(problemId)}`, {
    headers: getAuthHeaders(), signal,
  });
  if (!response.ok) throw await parseApiError(response, '복습 정보를 불러오지 못했습니다.');
  return normaliseReview(await response.json() as Omit<LearningProblemReview, 'version'> & { version?: number });
}

export async function updateLearningProblemReview(
  problemId: string,
  request: UpdateLearningProblemReviewRequest,
  signal?: AbortSignal,
): Promise<LearningProblemReview> {
  if (request.note.length > 5000) throw new Error('메모는 5,000자까지 저장할 수 있습니다.');
  const response = await fetch(`${LEARNING_API_PATH}/problems/${encodeURIComponent(problemId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw await parseApiError(response, '복습 정보를 저장하지 못했습니다.');
  return normaliseReview(await response.json() as Omit<LearningProblemReview, 'version'> & { version?: number });
}
