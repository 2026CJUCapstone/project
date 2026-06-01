import { useState } from "react";
import { DIFFICULTY_LEVELS } from "../services/problemApi";
import type { ProblemCreateRequest, TestCase, ProblemTag } from "../services/problemApi";
import { DIFFICULTY_LABELS } from "../constants/difficulty";
import { PROBLEM_TAG_OPTIONS } from "../constants/problemTags";

const TAG_OPTIONS: { value: ProblemTag; label: string }[] = Array.from(PROBLEM_TAG_OPTIONS);

interface Props {
  onClose: () => void;
  onSubmit: (data: ProblemCreateRequest) => void;
  initialData?: ProblemCreateRequest;
}

export function ProblemFormModal({ onClose, onSubmit, initialData }: Props) {
  const [title, setTitle] = useState(initialData?.title ?? "");
  const [difficulty, setDifficulty] = useState<ProblemCreateRequest["difficulty"]>(initialData?.difficulty ?? "iron5");
  const [tags, setTags] = useState<ProblemTag[]>(initialData?.tags ?? []);
  const [points, setPoints] = useState(initialData?.points ?? 100);
  const [description, setDescription] = useState(initialData?.description ?? "");
  const [testCases, setTestCases] = useState<TestCase[]>(initialData?.testCases?.length ? initialData.testCases : [{ input: "", expectedOutput: "" }]);
  const [hiddenTestCases, setHiddenTestCases] = useState<TestCase[]>(initialData?.hiddenTestCases?.length ? initialData.hiddenTestCases : [{ input: "", expectedOutput: "" }]);
  const [customTag, setCustomTag] = useState("");
  const [validationError, setValidationError] = useState("");

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
    const normalizedSamples = testCases.map((tc) => ({
      input: tc.input,
      expectedOutput: tc.expectedOutput,
    }));
    const normalizedHidden = hiddenTestCases
      .filter((tc) => tc.input.length > 0 || tc.expectedOutput.length > 0)
      .map((tc) => ({ input: tc.input, expectedOutput: tc.expectedOutput }));

    if (!title.trim() || !description.trim()) {
      setValidationError("제목과 문제 설명을 입력하세요.");
      return;
    }
    if (normalizedSamples.length === 0) {
      setValidationError("예제 채점을 최소 1개 이상 등록하세요.");
      return;
    }
    setValidationError("");
    onSubmit({
      title: title.trim(),
      difficulty,
      tags,
      points,
      description: description.trim(),
      testCases: normalizedSamples,
      hiddenTestCases: normalizedHidden,
    });
  };

  const addCustomTag = () => {
    const nextTag = customTag.trim().toLowerCase();
    if (!nextTag || tags.includes(nextTag)) return;
    if (!/^[a-z0-9_-]{1,32}$/.test(nextTag)) {
      setValidationError("커스텀 태그는 영문, 숫자, -, _ 조합으로 32자 이하만 사용할 수 있습니다.");
      return;
    }
    setTags((prev) => [...prev, nextTag]);
    setCustomTag("");
    setValidationError("");
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 flex flex-col gap-4"
      >
        <h2 className="text-lg font-bold text-gray-800">{initialData ? '문제 수정' : '문제 추가'}</h2>

        {validationError && (
          <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {validationError}
          </div>
        )}

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
            <div className="mt-2 flex gap-2">
              <input
                value={customTag}
                onChange={(event) => setCustomTag(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    addCustomTag();
                  }
                }}
                className="min-w-0 flex-1 border border-gray-300 rounded px-3 py-2 text-sm text-black outline-none focus:border-blue-500"
                placeholder="custom-tag"
              />
              <button
                type="button"
                onClick={addCustomTag}
                className="rounded border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                태그 추가
              </button>
            </div>
	        </div>

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">점수</label>
          <input
            type="number"
            min={0}
            max={10000}
            value={points}
            onChange={(e) => setPoints(Number(e.target.value))}
            className="border border-gray-300 rounded px-3 py-2 text-sm text-black outline-none focus:border-blue-500"
          />
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
          <label className="text-sm font-medium text-gray-700">예제 채점</label>
          {testCases.map((tc, idx) => (
	            <div key={idx} className="flex gap-2 items-start">
	              <div className="flex-1 grid grid-cols-1 gap-2 md:grid-cols-2">
	                <textarea
                    rows={3}
	                  placeholder={`입력 ${idx + 1}`}
	                  value={tc.input}
	                  onChange={(e) => updateTestCase(idx, "input", e.target.value)}
	                  className="resize-y border border-gray-300 rounded px-2 py-1.5 font-mono text-sm text-black outline-none focus:border-blue-500"
	                />
	                <textarea
                    rows={3}
	                  placeholder={`기대 출력 ${idx + 1}`}
	                  value={tc.expectedOutput}
	                  onChange={(e) => updateTestCase(idx, "expectedOutput", e.target.value)}
	                  className="resize-y border border-gray-300 rounded px-2 py-1.5 font-mono text-sm text-black outline-none focus:border-blue-500"
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
            + 예제 채점 추가
          </button>
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-700">채점</label>
          {hiddenTestCases.map((tc, idx) => (
	            <div key={idx} className="flex gap-2 items-start">
	              <div className="flex-1 grid grid-cols-1 gap-2 md:grid-cols-2">
	                <textarea
                    rows={3}
	                  placeholder={`채점 입력 ${idx + 1}`}
	                  value={tc.input}
	                  onChange={(e) => updateHiddenTestCase(idx, "input", e.target.value)}
	                  className="resize-y border border-gray-300 rounded px-2 py-1.5 font-mono text-sm text-black outline-none focus:border-blue-500"
	                />
	                <textarea
                    rows={3}
	                  placeholder={`채점 기대 출력 ${idx + 1}`}
	                  value={tc.expectedOutput}
	                  onChange={(e) => updateHiddenTestCase(idx, "expectedOutput", e.target.value)}
	                  className="resize-y border border-gray-300 rounded px-2 py-1.5 font-mono text-sm text-black outline-none focus:border-blue-500"
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
            + 채점 추가
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
