import { useState, useEffect, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { Home, ListChecks, Users, LogOut, Plus, Pencil, Trash2, ShieldCheck } from "lucide-react";
import { ProblemFormModal } from "../components/ProblemFormModal";
import { getProblems, createProblem, deleteProblem, updateProblem } from "../services/problemApi";
import type { Problem, ProblemCreateRequest } from "../services/problemApi";
import { getCurrentUser, login, type AuthUser } from "../services/authApi";
import { getAdminUsers, updateAdminUser, type AdminUser } from "../services/adminApi";
import { DIFFICULTY_LABELS } from "../constants/difficulty";

const difficultyLabel: Record<string, string> = {
  ...DIFFICULTY_LABELS,
};

export function Admin() {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [error, setError] = useState("");
  const [pageError, setPageError] = useState("");
  const [checkingSession, setCheckingSession] = useState(true);
  const [tab, setTab] = useState<"home" | "problems" | "users">("home");
  const [showForm, setShowForm] = useState(false);
  const [editingProblem, setEditingProblem] = useState<Problem | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);

  const loadProblems = useCallback(async () => {
    try {
      const data = await getProblems();
      setProblems(data);
      setPageError("");
    } catch (loadError) {
      setPageError(loadError instanceof Error ? loadError.message : "문제 목록을 불러오지 못했습니다.");
    }
  }, []);

  const loadUsers = useCallback(async () => {
    try {
      const data = await getAdminUsers();
      setUsers(data);
      setPageError("");
    } catch (loadError) {
      setPageError(loadError instanceof Error ? loadError.message : "사용자 목록을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    (async () => {
      if (!localStorage.getItem('authToken')) {
        setCheckingSession(false);
        return;
      }
      try {
        const me = await getCurrentUser();
        if (!mounted) return;
        if (me.role !== 'admin') {
          localStorage.removeItem('authToken');
          setError('관리자 권한이 필요합니다.');
          return;
        }
        setCurrentUser(me);
        setLoggedIn(true);
      } catch {
        if (mounted) localStorage.removeItem('authToken');
      } finally {
        if (mounted) setCheckingSession(false);
      }
    })();
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!loggedIn) return;
    void loadProblems();
    void loadUsers();
  }, [loggedIn, loadProblems, loadUsers]);

  const handleAddProblem = async (data: ProblemCreateRequest) => {
    try {
      if (editingProblem) {
        await updateProblem(editingProblem.id, data);
      } else {
        await createProblem(data);
      }
      await loadProblems();
      setPageError("");
    } catch (submitError) {
      setPageError(submitError instanceof Error ? submitError.message : "문제 저장에 실패했습니다.");
      return;
    }
    setShowForm(false);
    setEditingProblem(null);
  };

  const handleDeleteProblem = async (problemId: string) => {
    if (!window.confirm('정말 이 문제를 삭제하시겠습니까?')) return;
    try {
      await deleteProblem(problemId);
      await loadProblems();
    } catch (deleteError) {
      setPageError(deleteError instanceof Error ? deleteError.message : "문제 삭제에 실패했습니다.");
    }
  };

  const handleEditProblem = (problem: Problem) => {
    setEditingProblem(problem);
    setShowForm(true);
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const token = await login(id.trim(), password);
      localStorage.setItem('authToken', token.accessToken);
      const me = await getCurrentUser();
      if (me.role !== 'admin') {
        localStorage.removeItem('authToken');
        throw new Error('관리자 권한이 필요합니다.');
      }
      setCurrentUser(me);
      setLoggedIn(true);
    } catch (loginError) {
      setError(loginError instanceof Error ? loginError.message : "로그인에 실패했습니다.");
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('authToken');
    setLoggedIn(false);
    setCurrentUser(null);
  };

  const handleRoleChange = async (user: AdminUser, role: 'user' | 'admin') => {
    try {
      await updateAdminUser(user.id, { role });
      await loadUsers();
    } catch (roleError) {
      setPageError(roleError instanceof Error ? roleError.message : "권한 변경에 실패했습니다.");
    }
  };

  if (checkingSession) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#0d0d0d] text-gray-300">
        관리자 세션 확인 중...
      </div>
    );
  }

  if (loggedIn) {
    return (
      <div className="flex min-h-screen bg-[#0d0d0d] text-gray-100">
        {/* 사이드바 */}
        <aside className="w-64 bg-[#161616] border-r border-[#333] flex flex-col shrink-0">
          <div className="px-5 py-5 border-b border-[#333]">
            <h1 className="text-lg font-bold text-white">B++ 관리자</h1>
            {currentUser && <p className="text-xs text-gray-500 mt-1">{currentUser.username}</p>}
          </div>

          <nav className="flex flex-col py-4 flex-1">
            <button
              onClick={() => setTab("home")}
              className={`flex items-center gap-3 px-5 py-3.5 text-sm font-bold transition-colors ${
                tab === "home"
                  ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
                  : "text-gray-400 hover:bg-[#1e1e1e] hover:text-gray-200"
              }`}
            >
              <Home size={16} />
              Home
            </button>

            <span className="px-5 py-2 mt-4 text-xs font-semibold text-gray-500 uppercase tracking-wider">관리</span>
            <button
              onClick={() => setTab("problems")}
              className={`flex items-center gap-3 px-5 py-3.5 text-sm font-bold transition-colors ${
                tab === "problems"
                  ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
                  : "text-gray-400 hover:bg-[#1e1e1e] hover:text-gray-200"
              }`}
            >
              <ListChecks size={16} />
              문제 관리
            </button>
            <button
              onClick={() => setTab("users")}
              className={`flex items-center gap-3 px-5 py-3.5 text-sm font-bold transition-colors ${
                tab === "users"
                  ? "bg-blue-500/10 text-blue-400 border-r-2 border-blue-500"
                  : "text-gray-400 hover:bg-[#1e1e1e] hover:text-gray-200"
              }`}
            >
              <Users size={16} />
              사용자 관리
            </button>
          </nav>

          <div className="px-5 py-4 border-t border-[#333]">
            <button
              onClick={handleLogout}
              className="flex w-full items-center gap-2 text-sm text-gray-400 hover:text-gray-200 text-left"
            >
              <LogOut size={14} />
              로그아웃
            </button>
          </div>
        </aside>

        {/* 메인 콘텐츠 */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {/* 상단 헤더 */}
          <div className="flex items-center justify-between px-8 py-5 border-b border-[#333] bg-[#121212]">
            <h2 className="text-xl font-bold text-white">
              {tab === "home" ? "대시보드" : tab === "problems" ? "문제 관리" : "사용자 관리"}
            </h2>
          </div>

          {/* 콘텐츠 */}
          <div className="flex-1 overflow-y-auto p-8">
          {pageError && (
            <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {pageError}
            </div>
          )}
          {tab === "home" && (
            <div className="flex flex-col gap-6">
              <p className="text-gray-400">B++ 관리자 페이지에 오신 것을 환영합니다.</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6 cursor-pointer hover:border-blue-500 transition-colors" onClick={() => setTab("problems")}>
                  <ListChecks size={26} className="mb-2 text-blue-400" />
                  <h3 className="text-white font-bold mb-1">문제 관리</h3>
                  <p className="text-gray-500 text-sm">문제 {problems.length}개</p>
                </div>
                <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6 cursor-pointer hover:border-blue-500 transition-colors" onClick={() => setTab("users")}>
                  <Users size={26} className="mb-2 text-emerald-400" />
                  <h3 className="text-white font-bold mb-1">사용자 관리</h3>
                  <p className="text-gray-500 text-sm">사용자 {users.length}명</p>
                </div>
              </div>
            </div>
          )}

          {tab === "problems" && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-white">문제 목록</h2>
                <button
                  onClick={() => setShowForm(true)}
                  className="inline-flex items-center gap-2 bg-blue-500 text-white text-sm px-4 py-2 rounded hover:bg-blue-600"
                >
                  <Plus size={14} /> 문제 추가
                </button>
              </div>
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-[#333] text-left text-sm text-gray-400">
                    <th className="py-2 px-3">번호</th>
                    <th className="py-2 px-3">제목</th>
                    <th className="py-2 px-3">난이도</th>
                    <th className="py-2 px-3">점수</th>
                    <th className="py-2 px-3">태그</th>
                    <th className="py-2 px-3">채점</th>
                    <th className="py-2 px-3">관리</th>
                  </tr>
                </thead>
                <tbody>
                  {problems.length === 0 ? (
                    <tr className="text-sm text-gray-500 border-b border-[#222]">
                      <td className="py-3 px-3" colSpan={7}>
                        등록된 문제가 없습니다.
                      </td>
                    </tr>
                  ) : (
                    problems.map((p, idx) => (
                      <tr key={p.id} className="text-sm border-b border-[#222] hover:bg-[#1a1a1a]">
                        <td className="py-3 px-3 text-gray-400">{idx + 1}</td>
                        <td className="py-3 px-3 text-gray-200">{p.title}</td>
                        <td className="py-3 px-3 text-gray-400">{difficultyLabel[p.difficulty] ?? p.difficulty}</td>
                        <td className="py-3 px-3 text-gray-300">{p.points ?? 100}</td>
                        <td className="py-3 px-3">
                          <div className="flex gap-1 flex-wrap">
                            {(p.tags ?? []).map(tag => (
                              <span key={tag} className="px-1.5 py-0.5 text-xs rounded bg-blue-500/20 text-blue-300">
                                {tag === 'io' ? '입출력' : tag === 'control' ? '제어문' : '함수'}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <div className="flex flex-col gap-1 text-xs">
                            <span className="text-emerald-300">예제 채점 {(p.testCases ?? []).length}개</span>
                            <span className="text-amber-300">채점 {(p.hiddenTestCases ?? []).length}개</span>
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleEditProblem(p)}
                              className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 text-sm"
                            >
                              <Pencil size={13} /> 수정
                            </button>
                            <button
                              onClick={() => handleDeleteProblem(p.id)}
                              className="inline-flex items-center gap-1 text-red-500 hover:text-red-400 text-sm"
                            >
                              <Trash2 size={13} /> 삭제
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
              {showForm && (
                <ProblemFormModal
                  onClose={() => { setShowForm(false); setEditingProblem(null); }}
                  onSubmit={handleAddProblem}
                  initialData={editingProblem ? { title: editingProblem.title, difficulty: editingProblem.difficulty, tags: editingProblem.tags, points: editingProblem.points ?? 100, description: editingProblem.description, testCases: editingProblem.testCases, hiddenTestCases: editingProblem.hiddenTestCases } : undefined}
                />
              )}

              {/* 원형 그래프 */}
              <div className="grid grid-cols-2 gap-6 mt-8">
                  {/* 태그 비율 */}
                  <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6">
                    <h3 className="text-sm font-bold text-gray-300 mb-4 text-center">문제 태그 비율</h3>
                    {problems.length === 0 ? (
                      <div className="flex items-center justify-center h-[250px] text-gray-600 text-sm">데이터 없음</div>
                    ) : (
                    <ResponsiveContainer width="100%" height={250}>
                      <PieChart>
                        <Pie
                          data={(() => {
                            const counts: Record<string, number> = {};
                            problems.forEach(p => (p.tags ?? []).forEach(t => { counts[t] = (counts[t] || 0) + 1; }));
                            const labels: Record<string, string> = { io: '입출력', control: '제어문', func: '함수' };
                            return Object.entries(counts).map(([k, v]) => ({ name: labels[k] || k, value: v }));
                          })()}
                          cx="50%" cy="50%" outerRadius={80} dataKey="value" label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        >
                          {['#3b82f6', '#a855f7', '#ec4899'].map((color, i) => <Cell key={i} fill={color} />)}
                        </Pie>
                        <Tooltip contentStyle={{ background: '#1e1e1e', border: '1px solid #333', borderRadius: 8, color: '#fff' }} />
                        <Legend wrapperStyle={{ color: '#9ca3af', fontSize: 12 }} />
                      </PieChart>
                    </ResponsiveContainer>
                    )}
                  </div>

                  {/* 난이도 비율 */}
                  <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6">
                    <h3 className="text-sm font-bold text-gray-300 mb-4 text-center">문제 난이도 비율</h3>
                    {problems.length === 0 ? (
                      <div className="flex items-center justify-center h-[250px] text-gray-600 text-sm">데이터 없음</div>
                    ) : (
                    <ResponsiveContainer width="100%" height={250}>
                      <PieChart>
                        <Pie
                          data={(() => {
                            const counts: Record<string, number> = {};
                            problems.forEach(p => { counts[p.difficulty] = (counts[p.difficulty] || 0) + 1; });
                            const labels: Record<string, string> = DIFFICULTY_LABELS;
                            return Object.entries(counts).map(([k, v]) => ({ name: labels[k] || k, value: v }));
                          })()}
                          cx="50%" cy="50%" outerRadius={80} dataKey="value" label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                        >
                          {['#78716c', '#a16207', '#64748b', '#ca8a04', '#0891b2', '#2563eb'].map((color, i) => <Cell key={i} fill={color} />)}
                        </Pie>
                        <Tooltip contentStyle={{ background: '#1e1e1e', border: '1px solid #333', borderRadius: 8, color: '#fff' }} />
                        <Legend wrapperStyle={{ color: '#9ca3af', fontSize: 12 }} />
                      </PieChart>
                    </ResponsiveContainer>
                    )}
                  </div>
                </div>
            </div>
          )}

          {tab === "users" && (
            <div>
              <h2 className="text-lg font-semibold text-white mb-4">사용자 목록</h2>
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-[#333] text-left text-sm text-gray-400">
                    <th className="py-2 px-3">번호</th>
                    <th className="py-2 px-3">아이디</th>
                    <th className="py-2 px-3">닉네임</th>
                    <th className="py-2 px-3">점수</th>
                    <th className="py-2 px-3">권한</th>
                    <th className="py-2 px-3">관리</th>
                  </tr>
                </thead>
                <tbody>
                  {users.length === 0 ? (
                    <tr className="text-sm text-gray-500 border-b border-[#222]">
                      <td className="py-3 px-3" colSpan={6}>
                        등록된 사용자가 없습니다.
                      </td>
                    </tr>
                  ) : (
                    users.map((user, idx) => (
                      <tr key={user.id} className="text-sm border-b border-[#222] hover:bg-[#1a1a1a]">
                        <td className="py-3 px-3 text-gray-400">{idx + 1}</td>
                        <td className="py-3 px-3 text-gray-200">{user.username}</td>
                        <td className="py-3 px-3 text-gray-400">{user.nickname || '-'}</td>
                        <td className="py-3 px-3 text-gray-300">{user.totalScore}</td>
                        <td className="py-3 px-3">
                          <span className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs ${
                            user.role === 'admin' ? 'bg-blue-500/20 text-blue-300' : 'bg-gray-500/20 text-gray-300'
                          }`}>
                            {user.role === 'admin' && <ShieldCheck size={12} />}
                            {user.role === 'admin' ? '관리자' : '사용자'}
                          </span>
                        </td>
                        <td className="py-3 px-3">
                          <button
                            onClick={() => {
                              void handleRoleChange(user, user.role === 'admin' ? 'user' : 'admin');
                            }}
                            disabled={user.id === currentUser?.id}
                            className="text-blue-400 hover:text-blue-300 disabled:text-gray-600 disabled:cursor-not-allowed"
                          >
                            {user.role === 'admin' ? '사용자로 변경' : '관리자로 변경'}
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-[#0d0d0d] text-gray-100">
      <form onSubmit={handleLogin} className="flex flex-col gap-4 w-80">
        <h1 className="text-2xl font-bold text-center text-white">관리자 로그인</h1>
        <input
          type="text"
          placeholder="아이디"
          value={id}
          onChange={(e) => setId(e.target.value)}
          className="bg-[#1e1e1e] border border-[#333] text-gray-100 rounded px-3 py-2 outline-none focus:border-blue-500 placeholder-gray-500"
        />
        <input
          type="password"
          placeholder="비밀번호"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="bg-[#1e1e1e] border border-[#333] text-gray-100 rounded px-3 py-2 outline-none focus:border-blue-500 placeholder-gray-500"
        />
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <button
          type="submit"
          className="bg-blue-500 text-white rounded px-3 py-2 hover:bg-blue-600"
        >
          로그인
        </button>
      </form>
    </div>
  );
}
