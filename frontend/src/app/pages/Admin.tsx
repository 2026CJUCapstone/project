import { useState, useEffect, useCallback } from "react";
import { ProblemFormModal } from "../components/ProblemFormModal";
import { getProblems, createProblem, deleteProblem, updateProblem } from "../services/problemApi";
import type { Problem, ProblemCreateRequest } from "../services/problemApi";

const difficultyLabel: Record<string, string> = {
  beginner: "쉬움",
  intermediate: "보통",
  advanced: "어려움",
};

export function Admin() {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"problems" | "users">("problems");
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
      <div className="min-h-screen bg-[#0d0d0d] text-gray-100">
        {/* 상단 헤더 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#333]">
          <h1 className="text-xl font-bold text-white">관리자 페이지</h1>
          <button
            onClick={() => setLoggedIn(false)}
            className="text-sm text-gray-400 hover:text-gray-200"
          >
            로그아웃
          </button>
        </div>

        {/* 탭 */}
        <div className="flex border-b border-[#333]">
          <button
            onClick={() => setTab("problems")}
            className={`px-6 py-3 text-sm font-medium ${
              tab === "problems"
                ? "border-b-2 border-blue-500 text-blue-400"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            문제 관리
          </button>
          <button
            onClick={() => setTab("users")}
            className={`px-6 py-3 text-sm font-medium ${
              tab === "users"
                ? "border-b-2 border-blue-500 text-blue-400"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            사용자 관리
          </button>
        </div>

        {/* 탭 내용 */}
        <div className="p-6">
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
                    <th className="py-2 px-3">관리</th>
                  </tr>
                </thead>
                <tbody>
                  {problems.length === 0 ? (
                    <tr className="text-sm text-gray-500 border-b border-[#222]">
                      <td className="py-3 px-3" colSpan={5}>
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
                  initialData={editingProblem ? { title: editingProblem.title, difficulty: editingProblem.difficulty, tags: editingProblem.tags, description: editingProblem.description, testCases: editingProblem.testCases } : undefined}
                />
              )}
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
