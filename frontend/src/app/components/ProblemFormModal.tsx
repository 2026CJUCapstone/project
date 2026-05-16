import { useState } from "react";
import { DIFFICULTY_LEVELS } from "../services/problemApi";
import type { ProblemCreateRequest, TestCase, ProblemTag } from "../services/problemApi";
import { DIFFICULTY_LABELS } from "../constants/difficulty";

const TAG_OPTIONS: { value: ProblemTag; label: string }[] = [
  { value: 'io', label: '입출력' },
  { value: 'control', label: '제어문' },
  { value: 'func', label: '함수' },
];

interface Props {
  onClose: () => void;
  onSubmit: (data: ProblemCreateRequest) => void;
  initialData?: ProblemCreateRequest;
}

export function ProblemFormModal({ onClose, onSubmit, initialData }: Props) {
  const [title, setTitle] = useState(initialData?.title ?? "");
  const [difficulty, setDifficulty] = useState<ProblemCreateRequest["difficulty"]>(initialData?.difficulty ?? "iron5");
  const [tags, setTags] = useState<ProblemTag[]>(initialData?.tags ?? []);
  const [description, setDescription] = useState(initialData?.description ?? "");
  const [testCases, setTestCases] = useState<TestCase[]>(initialData?.testCases?.length ? initialData.testCases : [{ input: "", expectedOutput: "" }]);
  const [hiddenTestCases, setHiddenTestCases] = useState<TestCase[]>(initialData?.hiddenTestCases?.length ? initialData.hiddenTestCases : [{ input: "", expectedOutput: "" }]);

  const addTestCase = () => setTestCases([...testCases, { input: "", expectedOutput: "" }]);
  const addHiddenTestCase = () => setHiddenTestCases([...hiddenTestCases, { input: "", expectedOutput: "" }]);

  const removeTestCase = (idx: number) => {
    if (testCases.length <= 1) return;
    setTestCases(testCases.filter((_, i) => i !== idx));
  };

  const removeHiddenTestCase = (idx: number) => {
    if (hiddenTestCases.length <= 1) return;
    setHiddenTestCases(hiddenTestCases.filter((_, i) => i !== idx));
  };

  const updateTestCase = (idx: number, field: keyof TestCase, value: string) => {
    setTestCases(testCases.map((tc, i) => (i === idx ? { ...tc, [field]: value } : tc)));
  };

  const updateHiddenTestCase = (idx: number, field: keyof TestCase, value: string) => {
    setHiddenTestCases(hiddenTestCases.map((tc, i) => (i === idx ? { ...tc, [field]: value } : tc)));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !description.trim()) return;
    onSubmit({ title, difficulty, tags, description, testCases, hiddenTestCases });
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 flex flex-col gap-4"
      >
        <h2 className="text-lg font-bold text-gray-800">{initialData ? '문제 수정' : '문제 추가'}</h2>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">제목</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="border border-gray-300 rounded px-3 py-2 text-sm text-black outline-none focus:border-blue-500"
            placeholder="문제 제목"
          />
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">난이도</label>
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value as ProblemCreateRequest["difficulty"])}
            className="border border-gray-300 rounded px-3 py-2 text-sm text-black outline-none focus:border-blue-500"
          >
            {DIFFICULTY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {DIFFICULTY_LABELS[level]}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">분류 (태그)</label>
          <div className="flex gap-2 flex-wrap">
            {TAG_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() =>
                  setTags((prev) =>
                    prev.includes(opt.value)
                      ? prev.filter((t) => t !== opt.value)
                      : [...prev, opt.value]
                  )
                }
                className={`px-3 py-1.5 text-sm rounded border transition-colors ${
                  tags.includes(opt.value)
                    ? "bg-blue-500 text-white border-blue-500"
                    : "bg-white text-gray-600 border-gray-300 hover:border-blue-400"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">문제 설명</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            rows={4}
            className="border border-gray-300 rounded px-3 py-2 text-sm text-black outline-none focus:border-blue-500 resize-y"
            placeholder="문제 내용을 입력하세요"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-700">예시 테스트 케이스</label>
          {testCases.map((tc, idx) => (
            <div key={idx} className="flex gap-2 items-start">
              <div className="flex-1 flex flex-col gap-1">
                <input
                  type="text"
                  placeholder={`입력 ${idx + 1}`}
                  value={tc.input}
                  onChange={(e) => updateTestCase(idx, "input", e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm text-black outline-none focus:border-blue-500"
                />
                <input
                  type="text"
                  placeholder={`기대 출력 ${idx + 1}`}
                  value={tc.expectedOutput}
                  onChange={(e) => updateTestCase(idx, "expectedOutput", e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm text-black outline-none focus:border-blue-500"
                />
              </div>
              {testCases.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeTestCase(idx)}
                  className="text-red-400 hover:text-red-600 text-lg mt-1"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={addTestCase}
            className="text-sm text-blue-500 hover:text-blue-700 self-start"
          >
            + 예시 테스트 케이스 추가
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-700">숨김 테스트 케이스</label>
          {hiddenTestCases.map((tc, idx) => (
            <div key={idx} className="flex gap-2 items-start">
              <div className="flex-1 flex flex-col gap-1">
                <input
                  type="text"
                  placeholder={`숨김 입력 ${idx + 1}`}
                  value={tc.input}
                  onChange={(e) => updateHiddenTestCase(idx, "input", e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm text-black outline-none focus:border-blue-500"
                />
                <input
                  type="text"
                  placeholder={`숨김 기대 출력 ${idx + 1}`}
                  value={tc.expectedOutput}
                  onChange={(e) => updateHiddenTestCase(idx, "expectedOutput", e.target.value)}
                  className="border border-gray-300 rounded px-2 py-1.5 text-sm text-black outline-none focus:border-blue-500"
                />
              </div>
              {hiddenTestCases.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeHiddenTestCase(idx)}
                  className="text-red-400 hover:text-red-600 text-lg mt-1"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            onClick={addHiddenTestCase}
            className="text-sm text-blue-500 hover:text-blue-700 self-start"
          >
            + 숨김 테스트 케이스 추가
          </button>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 border border-gray-300 rounded hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="submit"
            className="px-4 py-2 text-sm text-white bg-blue-500 rounded hover:bg-blue-600"
          >
            저장
          </button>
        </div>
      </form>
    </div>
  );
}
