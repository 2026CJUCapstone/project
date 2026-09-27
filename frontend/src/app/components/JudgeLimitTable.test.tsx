import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { JudgeLimitTable } from './JudgeLimitTable';
import type { JudgePolicyLanguage, JudgePolicyLanguageLimits, PublicJudgeLimits } from '../services/judgePolicyTypes';

function limits(runtimeVersion: string, cpuMs: number, memoryBytes = 256 * 1024 ** 2): JudgePolicyLanguageLimits {
  return {
    runtimeVersion,
    compile: {
      cpuMs: cpuMs * 2,
      wallMs: cpuMs * 3,
      memoryBytes,
      outputBytes: 1024 ** 2,
      pids: 64,
      tmpBytes: 512 * 1024,
    },
    run: {
      cpuMs,
      wallMs: cpuMs + 250,
      memoryBytes,
      outputBytes: 1024 ** 2,
      pids: 64,
      tmpBytes: 512 * 1024,
    },
  };
}

function policy(reviewStatus: PublicJudgeLimits['reviewStatus'] = 'verified'): PublicJudgeLimits {
  const languages = Object.fromEntries([
    ['bpp', limits('B++ runtime 1.0', 1250)],
    ['c', limits('GCC 14', 1000)],
    ['cpp', limits('G++ 14', 1000)],
    ['python', limits('CPython 3.13', 2500)],
    ['java', limits('OpenJDK 21', 1750)],
    ['javascript', limits('Node.js 22', 2000)],
  ]) as Record<JudgePolicyLanguage, JudgePolicyLanguageLimits>;
  return { policyId: 'contest-2026', revision: 3, reviewStatus, languages };
}

describe('JudgeLimitTable', () => {
  it('updates the selected language summary while keeping every language in the compact table', () => {
    const { rerender } = render(<JudgeLimitTable policy={policy()} selectedLanguage="bpp" />);

    expect(screen.getByRole('heading', { name: 'B++ 실행 기준' })).toBeInTheDocument();
    expect(screen.getAllByText('1.25초')).not.toHaveLength(0);
    expect(screen.getByRole('table', { name: '언어별 채점 제한' })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'JavaScript' })).toBeInTheDocument();

    rerender(<JudgeLimitTable policy={policy()} selectedLanguage="python" />);

    expect(screen.getByRole('heading', { name: 'Python 실행 기준' })).toBeInTheDocument();
    expect(screen.getAllByText('2.5초')).not.toHaveLength(0);
    expect(screen.getByText('CPython 3.13')).toBeInTheDocument();
  });

  it('distinguishes unmeasured drafts, legacy records, and unsupported selected languages', () => {
    const { rerender } = render(<JudgeLimitTable policy={policy('draft')} selectedLanguage="bpp" />);
    expect(screen.getByRole('alert')).toHaveTextContent('초안 정책입니다. 실제 측정과 검증이 끝나기 전에는 제출 기준으로 사용하면 안 됩니다.');

    rerender(<JudgeLimitTable policy={null} selectedLanguage="bpp" legacy />);
    expect(screen.getByText('기존 문제 정책')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('현재 공통 제한을 추정해 표시하지 않습니다.');

    rerender(<JudgeLimitTable policy={policy()} selectedLanguage="ruby" />);
    expect(screen.getByRole('status')).toHaveTextContent('선택한 언어(ruby)는 이 정책에서 지원하지 않습니다.');
  });

  it('uses exact binary byte units in optional details and never renders malformed numeric values', () => {
    const malformed = policy();
    malformed.languages.bpp = {
      ...malformed.languages.bpp!,
      run: { ...malformed.languages.bpp!.run, cpuMs: Number.NaN, wallMs: -1, memoryBytes: -1 },
    };
    const { rerender } = render(<JudgeLimitTable policy={malformed} selectedLanguage="bpp" />);
    expect(screen.getAllByText('CPU 시간')[0].parentElement).toHaveTextContent('—');
    expect(screen.getAllByText('Wall 시간')[0].parentElement).toHaveTextContent('—');
    expect(screen.queryByText(/NaN|-0\.001/)).not.toBeInTheDocument();

    rerender(<JudgeLimitTable policy={policy()} selectedLanguage="bpp" />);
    fireEvent.click(screen.getByText('컴파일·출력·PID·임시 저장소 제한 자세히 보기'));
    expect(screen.getAllByText('1 MiB')).not.toHaveLength(0);
    expect(screen.getAllByText('512 KiB')).not.toHaveLength(0);
    expect(screen.getAllByText('256 MiB')).not.toHaveLength(0);
  });
});
