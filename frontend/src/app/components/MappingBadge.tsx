import type { MappingQualityInput } from '../services/mappingQuality';
import { classifyMapping } from '../services/mappingQuality';

const labels = { expression: '표현식 연결', statement: '문장 범위', scope: '함수·블록 범위', range: '소스 범위', approximate: '근사 연결', generated: '컴파일러 생성 · 소스 없음', unavailable: '소스 연결 없음' };
const descriptions = {
  expression: '컴파일러가 기록한 AST 표현식과 직접 연결됩니다.',
  statement: '개별 연산이 아니라 AST 문장 전체에 연결됩니다.',
  scope: '함수 또는 블록 전체 범위에 연결됩니다.',
  range: '소스 위치는 있지만 하나의 AST 표현식으로 확정할 수 없습니다.',
  approximate: '이전 형식의 위치 정보로 추정한 범위입니다.',
  generated: '컴파일러가 만든 항목이며 대응하는 소스 위치가 없습니다.',
  unavailable: '컴파일러 출력에 유효한 소스 위치가 없습니다.',
};
export function MappingBadge(props: MappingQualityInput) {
  const quality = classifyMapping(props);
  return <span data-mapping-quality={quality.kind} title={`${descriptions[quality.kind]}${props.generatedReason ? ` (${props.generatedReason})` : ''}`} className="inline-block max-w-full rounded border border-slate-300 px-1.5 py-0.5 text-[10px] font-normal text-slate-500 dark:border-neutral-600 dark:text-neutral-400">{labels[quality.kind]}</span>;
}
