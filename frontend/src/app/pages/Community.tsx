import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import {
  MessageSquare,
  Loader2,
  ChevronLeft,
  Send,
  Trash2,
  AlertTriangle,
  Cloud,
  HardDrive,
  LogIn,
  Megaphone,
  BookOpen,
  Coffee,
} from 'lucide-react';
import { getProblems, type Problem } from '../services/problemApi';
import {
  getSavedLeaderboardProfile,
  saveLeaderboardProfile,
  type LeaderboardProfile,
} from '../services/leaderboardProfile';
import { AuthModal } from '../components/AuthModal';
import {
  createCommunityPost,
  deleteCommunityPost,
  fetchCommunityPostCounts,
  fetchCommunityPosts,
  isCommunityRemoteConfigured,
  type CommunityPost,
} from '../services/communityApi';

type TabKey = 'notice' | 'problems' | 'free';

const NOTICE_BOARD_ID = '__notice__';
const FREE_BOARD_ID = '__free__';

const TAB_META: Record<TabKey, { label: string; icon: typeof Megaphone; description: string }> = {
  notice: {
    label: '공지',
    icon: Megaphone,
    description: '운영진 공지와 업데이트 소식을 확인하세요.',
  },
  problems: {
    label: '문제',
    icon: BookOpen,
    description: '문제별 풀이 아이디어와 질문을 나눠보세요.',
  },
  free: {
    label: '자유',
    icon: Coffee,
    description: '주제 제한 없이 자유롭게 이야기해보세요.',
  },
};

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

interface PostBoardProps {
  boardId: string;
  user: LeaderboardProfile | null;
  onRequireLogin: () => void;
  emptyMessage?: string;
  placeholder?: string;
  adminOnly?: boolean;
  initialDraft?: string;
}

function isAdminUser(user: LeaderboardProfile | null): boolean {
  return Boolean(user && user.name.trim().toLowerCase() === 'admin');
}

function PostBoard({
  boardId,
  user,
  onRequireLogin,
  emptyMessage,
  placeholder,
  adminOnly = false,
  initialDraft,
}: PostBoardProps) {
  const [posts, setPosts] = useState<CommunityPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState(initialDraft ?? '');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (initialDraft !== undefined) {
      setDraft(initialDraft);
    }
  }, [initialDraft]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    (async () => {
      try {
        const data = await fetchCommunityPosts(boardId);
        if (mounted) setPosts(data);
      } catch (e) {
        if (mounted) setError(e instanceof Error ? e.message : '게시글을 불러오지 못했습니다.');
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [boardId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (!content || submitting) return;
    if (!user) {
      onRequireLogin();
      return;
    }
    if (adminOnly && !isAdminUser(user)) {
      setError('관리자만 작성할 수 있습니다.');
      return;
    }
    setSubmitting(true);
    try {
      const created = await createCommunityPost({
        problemId: boardId,
        author: user.name.trim(),
        avatarUrl: user.avatar ?? null,
        content,
      });
      setPosts((prev) => [created, ...prev]);
      setDraft('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '게시글 작성에 실패했습니다.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    const prev = posts;
    setPosts((p) => p.filter((x) => x.id !== id));
    try {
      await deleteCommunityPost(id);
    } catch (err) {
      setPosts(prev);
      setError(err instanceof Error ? err.message : '삭제에 실패했습니다.');
    }
  };

  const canWrite = adminOnly ? isAdminUser(user) : true;
  const showWriter = canWrite || !adminOnly;

  return (
    <div>
      {showWriter ? (
        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616] p-4 mb-4"
        >
        {!user && (
          <div className="flex items-center justify-between gap-3 mb-3 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-700 dark:text-amber-300 text-xs">
            <span>게시글을 작성하려면 로그인이 필요합니다.</span>
            <button
              type="button"
              onClick={onRequireLogin}
              className="flex items-center gap-1 px-2 py-1 rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-800 dark:text-amber-200 font-semibold"
            >
              <LogIn size={12} /> 로그인
            </button>
          </div>
        )}
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={() => {
            if (!user) onRequireLogin();
          }}
          rows={3}
          placeholder={
            user
              ? placeholder ?? '생각을 공유해보세요...'
              : '로그인 후 게시글을 작성할 수 있습니다.'
          }
          className="w-full bg-transparent text-sm text-gray-900 dark:text-gray-100 outline-none resize-none placeholder:text-gray-400 dark:placeholder:text-gray-500 disabled:cursor-not-allowed"
          disabled={submitting || !user}
        />
        <div className="flex justify-end mt-2">
          {user ? (
            <button
              type="submit"
              disabled={!draft.trim() || submitting}
              className="flex items-center gap-2 px-4 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-sm font-semibold rounded-md disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              게시
            </button>
          ) : (
            <button
              type="button"
              onClick={onRequireLogin}
              className="flex items-center gap-2 px-4 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-sm font-semibold rounded-md transition-colors"
            >
              <LogIn size={14} /> 로그인하고 게시
            </button>
          )}
        </div>
      </form>
      ) : (
        <div className="flex items-center gap-2 mb-4 px-4 py-3 rounded-xl border border-dashed border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616] text-sm text-gray-500 dark:text-gray-400">
          <AlertTriangle size={16} className="text-amber-500" />
          공지는 관리자만 작성할 수 있습니다.
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 text-red-500 text-sm mb-3">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 py-6">
          <Loader2 className="animate-spin" size={16} /> 게시글을 불러오는 중...
        </div>
      ) : posts.length === 0 ? (
        <div className="text-center text-sm text-gray-500 dark:text-gray-400 py-8 border border-dashed border-gray-200 dark:border-[#333] rounded-xl">
          {emptyMessage ?? '아직 게시글이 없습니다. 첫 글을 남겨보세요!'}
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {posts.map((post) => (
            <li
              key={post.id}
              className="rounded-xl border border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616] p-4"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {post.avatarUrl ? (
                    <img
                      src={post.avatarUrl}
                      alt={post.author}
                      className="w-7 h-7 rounded-full object-cover"
                    />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-gray-200 dark:bg-[#2d2d2d] flex items-center justify-center text-xs font-semibold text-gray-600 dark:text-gray-300">
                      {post.author.slice(0, 1).toUpperCase()}
                    </div>
                  )}
                  <div>
                    <div className="text-sm font-semibold text-gray-900 dark:text-white">
                      {post.author}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {formatDate(post.createdAt)}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => {
                    void handleDelete(post.id);
                  }}
                  disabled={adminOnly && !isAdminUser(user)}
                  className="p-1.5 text-gray-400 hover:text-red-500 rounded transition-colors disabled:opacity-30 disabled:hover:text-gray-400 disabled:cursor-not-allowed"
                  title={adminOnly && !isAdminUser(user) ? '관리자만 삭제할 수 있습니다.' : '삭제'}
                >
                  <Trash2 size={14} />
                </button>
              </div>
              <p className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap">
                {post.content}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface ProblemBoardProps {
  user: LeaderboardProfile | null;
  onRequireLogin: () => void;
  initialProblemId?: string | null;
  initialDraft?: string;
}

function ProblemBoard({ user, onRequireLogin, initialProblemId, initialDraft }: ProblemBoardProps) {
  const [problems, setProblems] = useState<Problem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(initialProblemId ?? null);
  const [postCounts, setPostCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    if (initialProblemId) setSelectedId(initialProblemId);
  }, [initialProblemId]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await getProblems();
        if (!mounted) return;
        setProblems(data);
        try {
          const counts = await fetchCommunityPostCounts(data.map((p) => p.id));
          if (mounted) setPostCounts(counts);
        } catch {
          /* ignore */
        }
      } catch (e) {
        if (mounted) setError(e instanceof Error ? e.message : '문제를 불러오지 못했습니다.');
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  const selectedProblem = useMemo(
    () => problems.find((p) => p.id === selectedId) ?? null,
    [problems, selectedId],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
        <Loader2 className="animate-spin" size={18} /> 문제를 불러오는 중...
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-red-500">
        <AlertTriangle size={18} /> {error}
      </div>
    );
  }
  if (selectedProblem) {
    return (
      <section>
        <button
          onClick={() => setSelectedId(null)}
          className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white mb-4"
        >
          <ChevronLeft size={16} /> 문제 목록으로
        </button>

        <div className="rounded-xl border border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616] p-5 mb-4">
          <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-1">
            {selectedProblem.title}
          </h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-3">
            {selectedProblem.description}
          </p>
        </div>

        <PostBoard
          boardId={selectedProblem.id}
          user={user}
          onRequireLogin={onRequireLogin}
          placeholder="이 문제에 대한 생각을 공유해보세요..."
          initialDraft={initialDraft}
        />
      </section>
    );
  }
  if (problems.length === 0) {
    return (
      <div className="text-center text-sm text-gray-500 dark:text-gray-400 py-12 border border-dashed border-gray-200 dark:border-[#333] rounded-xl">
        등록된 문제가 없습니다.
      </div>
    );
  }
  return (
    <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {problems.map((problem) => (
        <li key={problem.id}>
          <button
            onClick={() => setSelectedId(problem.id)}
            className="w-full text-left rounded-xl border border-gray-200 dark:border-[#333] bg-white dark:bg-[#161616] hover:border-gray-300 dark:hover:border-[#555] hover:bg-gray-50 dark:hover:bg-[#1a1a1a] p-4 transition-colors"
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              <h3 className="text-base font-semibold text-gray-900 dark:text-white">
                {problem.title}
              </h3>
              <span className="flex items-center gap-1 text-xs text-purple-500 dark:text-purple-300 shrink-0">
                <MessageSquare size={12} /> {postCounts[problem.id] ?? 0}
              </span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2">
              {problem.description}
            </p>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function Community() {
  const location = useLocation();
  const navigate = useNavigate();
  const navState = (location.state ?? null) as
    | { tab?: TabKey; problemId?: string; problemTitle?: string }
    | null;

  const [tab, setTab] = useState<TabKey>(navState?.tab ?? 'notice');
  const [user, setUser] = useState<LeaderboardProfile | null>(null);
  const [isAuthOpen, setIsAuthOpen] = useState(false);
  const [pendingProblemId, setPendingProblemId] = useState<string | null>(
    navState?.problemId ?? null,
  );
  const [pendingDraft, setPendingDraft] = useState<string>(
    navState?.problemId
      ? `[문제 #${navState.problemId}·${navState.problemTitle ?? ''}] `
      : '',
  );

  const remoteConfigured = isCommunityRemoteConfigured();

  useEffect(() => {
    setUser(getSavedLeaderboardProfile());
  }, []);

  // 네비게이션 state 도착 시 탭/문제 자동 선택 후 state 제거 (새로고침 대비)
  useEffect(() => {
    if (navState && (navState.tab || navState.problemId)) {
      if (navState.tab) setTab(navState.tab);
      if (navState.problemId) {
        setPendingProblemId(navState.problemId);
        setPendingDraft(`[문제 #${navState.problemId}·${navState.problemTitle ?? ''}] `);
      }
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const tabMeta = TAB_META[tab];

  return (
    <div className="flex-1 overflow-y-auto bg-gray-50 dark:bg-[#0d0d0d]">
      <div className="max-w-5xl mx-auto px-6 py-8">
        <header className="mb-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <MessageSquare className="text-purple-500" size={24} />
              커뮤니티
            </h1>
            <span
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-md border ${
                remoteConfigured
                  ? 'text-green-600 border-green-500/40 bg-green-500/10'
                  : 'text-amber-600 border-amber-500/40 bg-amber-500/10'
              }`}
              title={
                remoteConfigured
                  ? '백엔드 API에 연결되어 게시글이 영속화됩니다.'
                  : 'VITE_COMMUNITY_API_URL 또는 VITE_API_URL 미설정 — 브라우저 로컬에만 저장됩니다.'
              }
            >
              {remoteConfigured ? <Cloud size={12} /> : <HardDrive size={12} />}
              {remoteConfigured ? '서버 저장' : '로컬 저장'}
            </span>
          </div>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{tabMeta.description}</p>
        </header>

        <div
          role="tablist"
          aria-label="커뮤니티 탭"
          className="flex items-center gap-1 mb-6 border-b border-gray-200 dark:border-[#333]"
        >
          {(Object.keys(TAB_META) as TabKey[]).map((key) => {
            const Icon = TAB_META[key].icon;
            const active = tab === key;
            return (
              <button
                key={key}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(key)}
                className={`flex items-center gap-2 px-4 py-2 -mb-px text-sm font-medium border-b-2 transition-colors ${
                  active
                    ? 'border-purple-500 text-purple-600 dark:text-purple-300'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white'
                }`}
              >
                <Icon size={14} />
                {TAB_META[key].label}
              </button>
            );
          })}
        </div>

        {tab === 'notice' && (
          <PostBoard
            boardId={NOTICE_BOARD_ID}
            user={user}
            onRequireLogin={() => setIsAuthOpen(true)}
            emptyMessage="아직 등록된 공지가 없습니다."
            placeholder="공지 사항을 작성하세요..."
            adminOnly
          />
        )}
        {tab === 'problems' && (
          <ProblemBoard
            user={user}
            onRequireLogin={() => setIsAuthOpen(true)}
            initialProblemId={pendingProblemId}
            initialDraft={pendingDraft}
          />
        )}
        {tab === 'free' && (
          <PostBoard
            boardId={FREE_BOARD_ID}
            user={user}
            onRequireLogin={() => setIsAuthOpen(true)}
            emptyMessage="아직 게시글이 없습니다. 첫 글을 남겨보세요!"
            placeholder="자유롭게 이야기를 나눠보세요..."
          />
        )}
      </div>

      <AuthModal
        isOpen={isAuthOpen}
        onClose={() => setIsAuthOpen(false)}
        onLogin={(name, avatar) => {
          const profile: LeaderboardProfile = { name, avatar };
          setUser(profile);
          saveLeaderboardProfile(profile);
        }}
      />
    </div>
  );
}
