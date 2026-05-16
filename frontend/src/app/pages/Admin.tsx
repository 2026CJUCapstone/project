import { useState, useEffect, useCallback } from "react";
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { ProblemFormModal } from "../components/ProblemFormModal";
import { getProblems, createProblem, deleteProblem, updateProblem } from "../services/problemApi";
import type { Problem, ProblemCreateRequest } from "../services/problemApi";
import { DIFFICULTY_LABELS } from "../constants/difficulty";

const difficultyLabel: Record<string, string> = {
  ...DIFFICULTY_LABELS,
};

export function Admin() {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"home" | "problems" | "users">("home");
  const [showForm, setShowForm] = useState(false);
  const [editingProblem, setEditingProblem] = useState<Problem | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);

  const loadProblems = useCallback(async () => {
    try {
      const data = await getProblems();
      setProblems(data);
    } catch {
      // API 미연동 시 빈 목록 유지
    }
  }, []);

  useEffect(() => {
    if (loggedIn) loadProblems();
  }, [loggedIn, loadProblems]);

  const handleAddProblem = async (data: ProblemCreateRequest) => {
    try {
      if (editingProblem) {
        await updateProblem(editingProblem.id, data);
      } else {
        await createProblem(data);
      }
      await loadProblems();
    } catch {
      // API 미연동 시 무시
    }
    setShowForm(false);
    setEditingProblem(null);
  };

  const handleDeleteProblem = async (problemId: string) => {
    if (!window.confirm('정말 이 문제를 삭제하시겠습니까?')) return;
    try {
      await deleteProblem(problemId);
      await loadProblems();
    } catch {
      // API 미연동 시 무시
    }
  };

  const handleEditProblem = (problem: Problem) => {
    setEditingProblem(problem);
    setShowForm(true);
  };

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    if (id === "admin" && password === "admin") {
      setLoggedIn(true);
      setError("");
    } else {
      setError("아이디 또는 비밀번호가 올바르지 않습니다.");
    }
  };

  if (loggedIn) {
    return (
      <div className="flex min-h-screen bg-[#0d0d0d] text-gray-100">
        {/* 사이드바 */}
        <aside className="w-64 bg-[#161616] border-r border-[#333] flex flex-col shrink-0">
          <div className="px-5 py-5 border-b border-[#333]">
            <h1 className="text-lg font-bold text-white">B++ 관리자</h1>
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
              <span className="text-base">🏠</span>
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
              <span className="text-base">📋</span>
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
              <span className="text-base">👥</span>
              사용자 관리
            </button>
          </nav>

          <div className="px-5 py-4 border-t border-[#333]">
            <button
              onClick={() => setLoggedIn(false)}
              className="w-full text-sm text-gray-400 hover:text-gray-200 text-left"
            >
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
          {tab === "home" && (
            <div className="flex flex-col gap-6">
              <p className="text-gray-400">B++ 관리자 페이지에 오신 것을 환영합니다.</p>
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6 cursor-pointer hover:border-blue-500 transition-colors" onClick={() => setTab("problems")}>
                  <span className="text-2xl mb-2 block">📋</span>
                  <h3 className="text-white font-bold mb-1">문제 관리</h3>
                  <p className="text-gray-500 text-sm">문제 추가, 수정, 삭제</p>
                </div>
                <div className="bg-[#1e1e1e] border border-[#333] rounded-lg p-6 cursor-pointer hover:border-blue-500 transition-colors" onClick={() => setTab("users")}>
                  <span className="text-2xl mb-2 block">👥</span>
                  <h3 className="text-white font-bold mb-1">사용자 관리</h3>
                  <p className="text-gray-500 text-sm">사용자 조회 및 관리</p>
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
                  className="bg-blue-500 text-white text-sm px-4 py-2 rounded hover:bg-blue-600"
                >
                  + 문제 추가
                </button>
              </div>
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-[#333] text-left text-sm text-gray-400">
                    <th className="py-2 px-3">번호</th>
                    <th className="py-2 px-3">제목</th>
                    <th className="py-2 px-3">난이도</th>
                    <th className="py-2 px-3">태그</th>
                    <th className="py-2 px-3">테스트</th>
                    <th className="py-2 px-3">관리</th>
                  </tr>
                </thead>
                <tbody>
                  {problems.length === 0 ? (
                    <tr className="text-sm text-gray-500 border-b border-[#222]">
                      <td className="py-3 px-3" colSpan={6}>
                        등록된 문제가 없습니다.
                      </td>
                    </tr>
                  ) : (
                    problems.map((p, idx) => (
                      <tr key={p.id} className="text-sm border-b border-[#222] hover:bg-[#1a1a1a]">
                        <td className="py-3 px-3 text-gray-400">{idx + 1}</td>
                        <td className="py-3 px-3 text-gray-200">{p.title}</td>
                        <td className="py-3 px-3 text-gray-400">{difficultyLabel[p.difficulty] ?? p.difficulty}</td>
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
                            <span className="text-emerald-300">예시 {(p.testCases ?? []).length}개</span>
                            <span className="text-amber-300">숨김 {(p.hiddenTestCases ?? []).length}개</span>
                          </div>
                        </td>
                        <td className="py-3 px-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleEditProblem(p)}
                              className="text-blue-400 hover:text-blue-300 text-sm"
                            >
                              수정
                            </button>
                            <button
                              onClick={() => handleDeleteProblem(p.id)}
                              className="text-red-500 hover:text-red-700 text-sm"
                            >
                              삭제
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
                  initialData={editingProblem ? { title: editingProblem.title, difficulty: editingProblem.difficulty, tags: editingProblem.tags, description: editingProblem.description, testCases: editingProblem.testCases, hiddenTestCases: editingProblem.hiddenTestCases } : undefined}
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
                    <th className="py-2 px-3">이름</th>
                    <th className="py-2 px-3">관리</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="text-sm text-gray-500 border-b border-[#222]">
                    <td className="py-3 px-3" colSpan={4}>
                      등록된 사용자가 없습니다.
                    </td>
                  </tr>
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
