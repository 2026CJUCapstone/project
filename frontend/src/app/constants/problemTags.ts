export const PROBLEM_TAG_OPTIONS = [
  { value: 'io', label: '입출력' },
  { value: 'control', label: '제어문' },
  { value: 'func', label: '함수' },
  { value: 'math', label: '수학' },
  { value: 'array', label: '배열' },
  { value: 'string', label: '문자열' },
  { value: 'loop', label: '반복문' },
  { value: 'condition', label: '조건문' },
  { value: 'sort', label: '정렬' },
  { value: 'search', label: '탐색' },
  { value: 'dp', label: 'DP' },
  { value: 'graph', label: '그래프' },
  { value: 'greedy', label: '그리디' },
  { value: 'implementation', label: '구현' },
] as const;

export type KnownProblemTag = (typeof PROBLEM_TAG_OPTIONS)[number]['value'];
export type ProblemTag = KnownProblemTag | string;

const tagLabels: Map<string, string> = new Map(PROBLEM_TAG_OPTIONS.map((tag) => [tag.value, tag.label]));

const tagColors = [
  'text-blue-300 bg-blue-500/10 border-blue-500/20',
  'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
  'text-amber-300 bg-amber-500/10 border-amber-500/20',
  'text-pink-300 bg-pink-500/10 border-pink-500/20',
  'text-cyan-300 bg-cyan-500/10 border-cyan-500/20',
  'text-violet-300 bg-violet-500/10 border-violet-500/20',
  'text-lime-300 bg-lime-500/10 border-lime-500/20',
];

export function getProblemTagLabel(tag: string): string {
  return tagLabels.get(tag) ?? tag;
}

export function getProblemTagClass(tag: string): string {
  const index = Math.abs(Array.from(tag).reduce((acc, char) => acc + char.charCodeAt(0), 0)) % tagColors.length;
  return tagColors[index];
}
