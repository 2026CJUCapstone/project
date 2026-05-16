// 커뮤니티(문제별 게시글) API 클라이언트
//
// ── 백엔드 연동 가이드 ────────────────────────────────────────────────
// 환경변수 하나만 설정하면 자동으로 백엔드 영속화 모드로 전환됩니다.
//   1) VITE_COMMUNITY_API_URL 가 설정돼 있으면 그 베이스 URL을 사용
//   2) 없으면 VITE_API_URL 을 사용 (compilerApi 와 동일 베이스)
//   3) 둘 다 비어있고, 동일 오리진의 백엔드가 살아 있으면 그 베이스 사용
//   4) 모두 실패하면 localStorage 폴백 (현재 브라우저에만 저장)
//
// 백엔드가 구현해야 할 REST 엔드포인트 (스키마는 CommunityPost 참고):
//   GET    {BASE}/api/v1/community/posts?problemId={id}    → CommunityPost[]
//   POST   {BASE}/api/v1/community/posts                   → CommunityPost
//          body: CommunityPostCreateRequest
//   DELETE {BASE}/api/v1/community/posts/{postId}          → 204
//
// 응답 필드명은 snake_case / camelCase 모두 허용하도록 normalize 합니다.
// ─────────────────────────────────────────────────────────────────────

export interface CommunityPost {
  id: string;
  problemId: string;
  author: string;
  avatarUrl?: string | null;
  content: string;
  createdAt: string; // ISO-8601
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
const STORAGE_KEY = 'bpp.community.posts.v1';

function getAuthHeader(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem('authToken');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ── localStorage 폴백 ──────────────────────────────────────────────
function loadLocalPosts(): CommunityPost[] {
  try {
    const raw = typeof window !== 'undefined' ? window.localStorage.getItem(STORAGE_KEY) : null;
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as CommunityPost[]) : [];
  } catch {
    return [];
  }
}

function saveLocalPosts(posts: CommunityPost[]): void {
  try {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(posts));
    }
  } catch {
    /* ignore quota errors */
  }
}

// ── 응답 정규화 ─────────────────────────────────────────────────────
function normalizePost(raw: unknown): CommunityPost {
  const r = (raw ?? {}) as Record<string, unknown>;
  const get = (a: string, b: string): unknown => (r[a] !== undefined ? r[a] : r[b]);
  return {
    id: String(get('id', 'id') ?? ''),
    problemId: String(get('problemId', 'problem_id') ?? ''),
    author: String(get('author', 'author') ?? '익명'),
    avatarUrl: (get('avatarUrl', 'avatar_url') as string | null | undefined) ?? null,
    content: String(get('content', 'content') ?? ''),
    createdAt: String(get('createdAt', 'created_at') ?? new Date().toISOString()),
  };
}

// ── 원격 백엔드 가용성 캐시 ─────────────────────────────────────────
let remoteAvailable: boolean | null = null;

async function tryRemote<T>(fn: () => Promise<T>): Promise<T | null> {
  if (remoteAvailable === false) return null;
  try {
    const res = await fn();
    remoteAvailable = true;
    return res;
  } catch (err) {
    // 네트워크 오류, 404 등이면 폴백으로 전환하고 그 후로는 시도하지 않음
    if (remoteAvailable === null) {
      // eslint-disable-next-line no-console
      console.warn('[community] 백엔드 연결 실패, localStorage 폴백을 사용합니다.', err);
    }
    remoteAvailable = false;
    return null;
  }
}

// ── 공개 API ────────────────────────────────────────────────────────
export function isCommunityRemoteConfigured(): boolean {
  return Boolean(COMMUNITY_API_BASE_URL);
}

export async function fetchCommunityPosts(problemId: string): Promise<CommunityPost[]> {
  if (COMMUNITY_API_BASE_URL) {
    const remote = await tryRemote(async () => {
      const url = `${COMMUNITY_API_BASE_URL}${POSTS_PATH}?problemId=${encodeURIComponent(problemId)}`;
      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return Array.isArray(data) ? data.map(normalizePost) : [];
    });
    if (remote) return remote;
  }
  return loadLocalPosts()
    .filter((p) => p.problemId === problemId)
    .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export async function createCommunityPost(
  payload: CommunityPostCreateRequest,
): Promise<CommunityPost> {
  if (COMMUNITY_API_BASE_URL) {
    const remote = await tryRemote(async () => {
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
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return normalizePost(await res.json());
    });
    if (remote) return remote;
  }
  // 로컬 폴백
  const newPost: CommunityPost = {
    id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    problemId: payload.problemId,
    author: payload.author,
    avatarUrl: payload.avatarUrl ?? null,
    content: payload.content,
    createdAt: new Date().toISOString(),
  };
  const all = loadLocalPosts();
  saveLocalPosts([newPost, ...all]);
  return newPost;
}

export async function deleteCommunityPost(postId: string): Promise<void> {
  if (COMMUNITY_API_BASE_URL && !postId.startsWith('local-')) {
    const remote = await tryRemote(async () => {
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
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
      return true;
    });
    if (remote) return;
  }
  const all = loadLocalPosts();
  saveLocalPosts(all.filter((p) => p.id !== postId));
}

// 문제별 게시글 수 집계 (목록 화면용). 원격이 있으면 단일 호출 시도 후 실패시 로컬 집계.
export async function fetchCommunityPostCounts(
  problemIds: string[],
): Promise<Record<string, number>> {
  if (COMMUNITY_API_BASE_URL) {
    const remote = await tryRemote(async () => {
      const url = `${COMMUNITY_API_BASE_URL}${POSTS_PATH}/counts`;
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ problemIds, problem_ids: problemIds }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as Record<string, number>;
      return data ?? {};
    });
    if (remote) return remote;
  }
  const counts: Record<string, number> = {};
  for (const p of loadLocalPosts()) {
    counts[p.problemId] = (counts[p.problemId] ?? 0) + 1;
  }
  return counts;
}
