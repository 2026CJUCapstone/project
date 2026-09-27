import type { JudgeResourceUsage, JudgeResourceUsageStage, JudgeRunResourceUsage } from '../services/judgeMetricsTypes';

export interface SubmissionResourceUsageProps {
  resourceUsage?: JudgeResourceUsage | null;
  className?: string;
}

function formatNumber(value: number, maximumFractionDigits = 2): string {
  if (!Number.isFinite(value) || value < 0) return '—';
  return value.toLocaleString('ko-KR', { maximumFractionDigits });
}

function formatMilliseconds(value: number): string {
  const formatted = formatNumber(value, 3);
  return formatted === '—' ? formatted : `${formatted}ms`;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '—';
  if (value < 1024) return `${formatNumber(value, 0)} B`;

  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  const unitIndex = Math.min(Math.floor(Math.log(value) / Math.log(1024)) - 1, units.length - 1);
  const unitSize = 1024 ** (unitIndex + 1);
  return `${formatNumber(value / unitSize)} ${units[unitIndex]}`;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] leading-4 text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="mt-0.5 break-words font-mono text-xs font-medium text-slate-800 dark:text-slate-100">{value}</dd>
    </div>
  );
}

function CompileMetrics({ compile }: { compile: JudgeResourceUsageStage }) {
  return (
    <section aria-label="컴파일 자원 사용량" className="rounded border border-slate-200 bg-white p-2.5 dark:border-slate-700 dark:bg-slate-900">
      <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-100">컴파일</h4>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2">
        <Metric label="CPU" value={formatMilliseconds(compile.cpuMs)} />
        <Metric label="Wall" value={formatMilliseconds(compile.wallMs)} />
        <Metric label="메모리 최대" value={formatBytes(compile.peakMemoryBytes)} />
      </dl>
    </section>
  );
}

function RunMetrics({ run }: { run: JudgeRunResourceUsage }) {
  return (
    <section aria-label="실행 자원 사용량" className="rounded border border-slate-200 bg-white p-2.5 dark:border-slate-700 dark:bg-slate-900">
      <h4 className="text-xs font-semibold text-slate-800 dark:text-slate-100">실행</h4>
      <p className="mt-0.5 text-[11px] leading-4 text-slate-500 dark:text-slate-400">CPU·Wall은 실행된 모든 케이스의 합계입니다.</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2">
        <Metric label="CPU 합계" value={formatMilliseconds(run.cpuMs)} />
        <Metric label="Wall 합계" value={formatMilliseconds(run.wallMs)} />
        <Metric label="메모리 최대" value={formatBytes(run.peakMemoryBytes)} />
        <Metric label="케이스 최대 CPU" value={formatMilliseconds(run.maxCpuMs)} />
        <Metric label="케이스 최대 Wall" value={formatMilliseconds(run.maxWallMs)} />
      </dl>
    </section>
  );
}

/** Compact, public-safe aggregate usage display. It deliberately exposes no case-level data. */
export function SubmissionResourceUsage({ resourceUsage, className = '' }: SubmissionResourceUsageProps) {
  if (!resourceUsage) {
    return <span role="status" className={`text-xs text-slate-500 dark:text-slate-400 ${className}`.trim()}>이전 채점 기록 · 자원 사용량 없음</span>;
  }

  const summary = resourceUsage.run
    ? {
      cpuLabel: '실행 CPU 최대',
      cpuValue: formatMilliseconds(resourceUsage.run.maxCpuMs),
      memoryLabel: '실행 메모리 최대',
      memoryValue: formatBytes(resourceUsage.run.peakMemoryBytes),
    }
    : {
      cpuLabel: '컴파일 CPU',
      cpuValue: formatMilliseconds(resourceUsage.compile.cpuMs),
      memoryLabel: '컴파일 메모리 최대',
      memoryValue: formatBytes(resourceUsage.compile.peakMemoryBytes),
    };

  return (
    <details className={`min-w-0 max-w-full rounded border border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 ${className}`.trim()}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-1.5 gap-y-0.5 px-2.5 py-2 text-xs font-medium leading-5 marker:hidden [&::-webkit-details-marker]:hidden">
        <span>{summary.cpuLabel} {summary.cpuValue}</span>
        <span aria-hidden="true" className="text-slate-400 dark:text-slate-500">·</span>
        <span>{summary.memoryLabel} {summary.memoryValue}</span>
        <span className="ml-auto whitespace-nowrap text-[11px] font-normal text-blue-700 dark:text-blue-300">상세</span>
      </summary>
      <div className="border-t border-slate-200 px-2.5 py-2.5 dark:border-slate-700">
        <p className="text-[11px] leading-4 text-slate-500 dark:text-slate-400">
          전체 단계(cgroup v2) 측정값입니다. 런타임·감독 프로세스와 tmpfs를 포함하므로 프로그램 RSS만을 뜻하지 않습니다.
        </p>
        <p className="mt-1 break-all text-[11px] leading-4 text-slate-500 dark:text-slate-400">정책 {resourceUsage.policyId} · 개정 {formatNumber(resourceUsage.policyRevision, 0)}</p>
        <div className="mt-2 grid gap-2">
          <CompileMetrics compile={resourceUsage.compile} />
          {resourceUsage.run ? <RunMetrics run={resourceUsage.run} /> : (
            <p role="status" className="rounded border border-slate-200 bg-white px-2.5 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              실행 단계는 기록되지 않았습니다.
            </p>
          )}
        </div>
      </div>
    </details>
  );
}
