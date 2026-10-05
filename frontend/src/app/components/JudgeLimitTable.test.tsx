import { fireEvent, render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { MemoryRouter } from 'react-router';
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
    ['python', limits('CPython 3.13', 2500, 512 * 1024 ** 2)],
    ['java', limits('OpenJDK 21', 1750)],
    ['javascript', limits('Node.js 22', 2000)],
  ]) as Record<JudgePolicyLanguage, JudgePolicyLanguageLimits>;
  return { policyId: 'contest-2026', revision: 3, reviewStatus, languages };
}

function renderTable(props: ComponentProps<typeof JudgeLimitTable>) {
  return render(
    <MemoryRouter>
      <JudgeLimitTable {...props} />
    </MemoryRouter>,
  );
}

describe('JudgeLimitTable', () => {
  it('renders a compact selected-language summary and links to judging help by default', () => {
    renderTable({ policy: policy('compatibility'), selectedLanguage: 'python', compatibility: true });

    expect(screen.getByRole('heading', { name: 'Python 채점 제한' })).toBeInTheDocument();
    expect(screen.getByText('2.5초')).toBeInTheDocument();
    expect(screen.getByText('2.75초')).toBeInTheDocument();
    expect(screen.getByText('512 MiB')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '채점 도움말' })).toHaveAttribute('href', '/help/judging');

    expect(screen.queryByRole('table', { name: '언어별 채점 제한' })).not.toBeInTheDocument();
    expect(screen.queryByText('기존 문제 호환 정책')).not.toBeInTheDocument();
    expect(screen.queryByText(/기존 문제에 적용되는 고정 호환 제한/)).not.toBeInTheDocument();
    expect(screen.queryByText(/컴파일·출력·PID·임시 저장소 제한 자세히 보기/)).not.toBeInTheDocument();
  });

  it('uses the optional local help link without changing the compact summary', () => {
    renderTable({ policy: policy(), selectedLanguage: 'bpp', helpTo: '/help/judging?problem=problem%2F1&language=bpp' });

    expect(screen.getByRole('link', { name: '채점 도움말' })).toHaveAttribute(
      'href',
      '/help/judging?problem=problem%2F1&language=bpp',
    );
    expect(screen.getByRole('heading', { name: 'B++ 채점 제한' })).toBeInTheDocument();
  });

  it('keeps the short draft warning, missing-policy message, and unsupported-language message', () => {
    const { rerender } = renderTable({ policy: policy('draft'), selectedLanguage: 'bpp' });
    expect(screen.getByRole('alert')).toHaveTextContent('검증 전 제한입니다. 제출 기준으로 사용하지 마세요.');
    expect(screen.queryByText(/초안 정책입니다/)).not.toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <JudgeLimitTable policy={null} selectedLanguage="bpp" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('채점 제한 정보가 없습니다.');

    rerender(
      <MemoryRouter>
        <JudgeLimitTable policy={policy()} selectedLanguage="ruby" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'ruby 채점 제한' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('선택한 언어(ruby)는 이 문제에서 지원하지 않습니다.');
  });

  it('renders malformed numeric values as em dashes instead of falling back', () => {
    const malformed = policy();
    malformed.languages.python = {
      ...malformed.languages.python!,
      run: { ...malformed.languages.python!.run, cpuMs: Number.NaN, wallMs: -1, memoryBytes: Number.POSITIVE_INFINITY },
    };
    renderTable({ policy: malformed, selectedLanguage: 'python' });

    expect(screen.getByText('CPU 시간').parentElement).toHaveTextContent('—');
    expect(screen.getByText('Wall 시간').parentElement).toHaveTextContent('—');
    expect(screen.getByText('메모리').parentElement).toHaveTextContent('—');
    expect(screen.queryByText(/NaN|-0\.001|Infinity/)).not.toBeInTheDocument();
  });

  it('preserves the full policy, stage details, badges, and all-language table in detailed mode', () => {
    renderTable({
      policy: policy('compatibility'),
      selectedLanguage: 'python',
      legacy: true,
      compatibility: true,
      detailed: true,
    });

    expect(screen.getByRole('heading', { name: '채점 제한' })).toBeInTheDocument();
    expect(screen.getByText('정책 contest-2026 · 개정 3')).toBeInTheDocument();
    expect(screen.getByText('기존 문제 정책')).toBeInTheDocument();
    expect(screen.getByText('기존 문제 호환 정책')).toBeInTheDocument();
    expect(screen.getByText(/기존 문제에 적용되는 고정 호환 제한/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Python 실행 기준' })).toBeInTheDocument();
    expect(screen.getByText('런타임 CPython 3.13')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: '언어별 채점 제한' })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'JavaScript' })).toBeInTheDocument();

    fireEvent.click(screen.getByText('컴파일·출력·PID·임시 저장소 제한 자세히 보기'));
    expect(screen.getByRole('region', { name: '컴파일 제한' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '실행 제한' })).toBeInTheDocument();
  });

  it('keeps the old detailed warning and fallback messages', () => {
    const { rerender } = renderTable({ policy: policy('draft'), selectedLanguage: 'bpp', detailed: true });
    expect(screen.getByRole('alert')).toHaveTextContent('초안 정책입니다. 실제 측정과 검증이 끝나기 전에는 제출 기준으로 사용하면 안 됩니다.');

    rerender(
      <MemoryRouter>
        <JudgeLimitTable policy={null} selectedLanguage="bpp" legacy detailed />
      </MemoryRouter>,
    );
    expect(screen.getByText('기존 문제 정책')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('현재 공통 제한을 추정해 표시하지 않습니다.');

    rerender(
      <MemoryRouter>
        <JudgeLimitTable policy={null} selectedLanguage="bpp" detailed />
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('이 문제에는 확정된 언어별 제한이 아직 없습니다.');

    rerender(
      <MemoryRouter>
        <JudgeLimitTable policy={policy()} selectedLanguage="ruby" detailed />
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('선택한 언어(ruby)는 이 정책에서 지원하지 않습니다.');
  });
});
