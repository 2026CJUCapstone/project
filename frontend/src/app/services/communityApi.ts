// 커뮤니티(문제별 게시글) API 클라이언트

export interface CommunityPost {
  id: string;
  problemId: string;
  userId?: string;
  author: string;
  avatarUrl?: string | null;
  content: string;
  createdAt: string; // ISO-8601
  canDelete?: boolean;
}

export interface CommunityPostCreateRequest {
  problemId: string;
  author: string;
  avatarUrl?: string | null;
  content: string;
}

function normalizeBase(value: string | undefined): string {
  if (!value || value === '/') return '';
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

const apiBaseFromBaseUrl =
  import.meta.env.BASE_URL === '/' ? '' : import.meta.env.BASE_URL.replace(/\/$/, '');

// 우선순위: 전용 변수 → 공용 API 변수 → BASE_URL
const COMMUNITY_API_BASE_URL = normalizeBase(
  import.meta.env.VITE_COMMUNITY_API_URL ||
    import.meta.env.VITE_API_URL ||
    apiBaseFromBaseUrl,
);

const POSTS_PATH = '/api/v1/community/posts';

function getAuthHeader(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem('authToken');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── 응답 정규화 ─────────────────────────────────────────────────────
function normalizePost(raw: unknown): CommunityPost {
  const r = (raw ?? {}) as Record<string, unknown>;
  const get = (a: string, b: string): unknown => (r[a] !== undefined ? r[a] : r[b]);
  return {
    id: String(get('id', 'id') ?? ''),
    problemId: String(get('problemId', 'problem_id') ?? ''),
    userId: String(get('userId', 'user_id') ?? '') || undefined,
    author: String(get('author', 'author') ?? '익명'),
    avatarUrl: (get('avatarUrl', 'avatar_url') as string | null | undefined) ?? null,
    content: String(get('content', 'content') ?? ''),
    createdAt: String(get('createdAt', 'created_at') ?? new Date().toISOString()),
    canDelete: Boolean(get('canDelete', 'can_delete') ?? false),
  };
}

// ── 공개 API ────────────────────────────────────────────────────────
export function isCommunityRemoteConfigured(): boolean {
  return true;
}

export async function fetchCommunityPosts(problemId: string): Promise<CommunityPost[]> {
  const url = `${COMMUNITY_API_BASE_URL}${POSTS_PATH}?problemId=${encodeURIComponent(problemId)}`;
  const res = await fetch(url, { headers: { Accept: 'application/json', ...getAuthHeader() } });
  if (!res.ok) {
    const errorData = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail || '게시글을 불러오지 못했습니다.');
  }
  const data = await res.json();
  return Array.isArray(data) ? data.map(normalizePost) : [];
}

export async function createCommunityPost(
  payload: CommunityPostCreateRequest,
): Promise<CommunityPost> {
  const res = await fetch(`${COMMUNITY_API_BASE_URL}${POSTS_PATH}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...getAuthHeader(),
    },
    body: JSON.stringify({
      problemId: payload.problemId,
      problem_id: payload.problemId,
      author: payload.author,
      avatarUrl: payload.avatarUrl ?? null,
      avatar_url: payload.avatarUrl ?? null,
      content: payload.content,
    }),
  });
  if (!res.ok) {
    const errorData = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail || '게시글 작성에 실패했습니다.');
  }
  return normalizePost(await res.json());
}

export async function deleteCommunityPost(postId: string): Promise<void> {
  const res = await fetch(
    `${COMMUNITY_API_BASE_URL}${POSTS_PATH}/${encodeURIComponent(postId)}`,
    {
      method: 'DELETE',
      headers: {
        Accept: 'application/json',
        ...getAuthHeader(),
      },
    },
  );
  if (!res.ok && res.status !== 204) {
    const errorData = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail || '삭제에 실패했습니다.');
  }
}

// 문제별 게시글 수 집계 (목록 화면용). 원격이 있으면 단일 호출 시도 후 실패시 로컬 집계.
export async function fetchCommunityPostCounts(
  problemIds: string[],
): Promise<Record<string, number>> {
  const url = `${COMMUNITY_API_BASE_URL}${POSTS_PATH}/counts`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ problemIds, problem_ids: problemIds }),
  });
  if (!res.ok) {
    const errorData = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail || '게시글 수를 불러오지 못했습니다.');
  }
  const data = (await res.json()) as Record<string, number>;
  return data ?? {};
}
