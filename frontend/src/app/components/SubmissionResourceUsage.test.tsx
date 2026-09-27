import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SubmissionResourceUsage } from './SubmissionResourceUsage';
import type { JudgeResourceUsage } from '../services/judgeMetricsTypes';

function usage(run: JudgeResourceUsage['run'] = {
  cpuMs: 210,
  wallMs: 340,
  maxCpuMs: 45,
  maxWallMs: 72,
  peakMemoryBytes: 64 * 1024 ** 2,
}): JudgeResourceUsage {
  return {
    version: 1,
    measurement: 'cgroup-v2-whole-phase',
    policyId: 'practice-2026',
    policyRevision: 4,
    compile: { cpuMs: 75, wallMs: 95, peakMemoryBytes: 96 * 1024 ** 2 },
    run,
  };
}

describe('SubmissionResourceUsage', () => {
  it('summarizes run measurements without blending in a more expensive compile phase', () => {
    render(<SubmissionResourceUsage resourceUsage={usage()} />);

    expect(screen.getByText('실행 CPU 최대 45ms')).toBeInTheDocument();
    expect(screen.getByText('실행 메모리 최대 64 MiB')).toBeInTheDocument();
    expect(screen.queryByText('실행 CPU 최대 75ms')).not.toBeInTheDocument();
    expect(screen.queryByText('실행 메모리 최대 96 MiB')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('실행 CPU 최대 45ms'));

    expect(screen.getByRole('region', { name: '컴파일 자원 사용량' })).toHaveTextContent('CPU75ms');
    expect(screen.getByRole('region', { name: '실행 자원 사용량' })).toHaveTextContent('CPU 합계210ms');
    expect(screen.getByRole('region', { name: '실행 자원 사용량' })).toHaveTextContent('케이스 최대 Wall72ms');
    expect(screen.getByText(/전체 단계\(cgroup v2\) 측정값/)).toHaveTextContent('런타임·감독 프로세스와 tmpfs를 포함');
    expect(screen.getByText('정책 practice-2026 · 개정 4')).toBeInTheDocument();
  });

  it('labels a null or missing record as unrecorded instead of treating it as zero usage', () => {
    const { rerender } = render(<SubmissionResourceUsage resourceUsage={null} />);

    expect(screen.getByRole('status')).toHaveTextContent('자원 측정 미기록');
    expect(screen.queryByText(/0ms|0 B/)).not.toBeInTheDocument();

    rerender(<SubmissionResourceUsage />);
    expect(screen.getByRole('status')).toHaveTextContent('자원 측정 미기록');
  });

  it('keeps compilation measurements distinct when the run phase was not recorded', () => {
    render(<SubmissionResourceUsage resourceUsage={usage(null)} />);

    expect(screen.getByText('컴파일 CPU 75ms')).toBeInTheDocument();
    expect(screen.getByText('컴파일 메모리 최대 96 MiB')).toBeInTheDocument();
    fireEvent.click(screen.getByText('컴파일 CPU 75ms'));
    expect(screen.getByRole('status')).toHaveTextContent('실행 단계는 기록되지 않았습니다.');
  });
});
