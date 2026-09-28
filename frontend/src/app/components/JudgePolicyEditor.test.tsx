import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { JudgePolicyEditor } from './JudgePolicyEditor';
import type { JudgePolicy, JudgePolicyLanguage, JudgePolicyRuntimeLimits } from '../services/judgePolicyTypes';
import { parseImportedJudgePolicy } from '../services/judgePolicyTypes';

const digest = (character: string) => `sha256:${character.repeat(64)}`;

function profile(runtimeVersion: string, cpuMs: number): JudgePolicyRuntimeLimits {
  return {
    runtimeId: `runtime-${cpuMs}`, runtimeVersion, imageDigest: digest('a'), workerClass: 'linux-amd64', toolchainProfile: 'standard',
    compile: { cpuMs: cpuMs * 2, wallMs: cpuMs * 3, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
    run: { cpuMs, wallMs: cpuMs + 250, memoryBytes: 256 * 1024 ** 2, outputBytes: 1024 ** 2, pids: 64, tmpBytes: 512 * 1024 },
  };
}

function policy(reviewStatus: JudgePolicy['reviewStatus'] = 'verified'): JudgePolicy {
  const profiles = {
    bpp: profile('B++ 1.0', 1250),
    python: profile('CPython 3.13', 2750),
  } satisfies Partial<Record<JudgePolicyLanguage, JudgePolicyRuntimeLimits>>;
  return {
    schemaVersion: 1, policyId: 'freshman-2026', revision: 4, reviewStatus, testSuiteHash: digest('b'), profiles,
    ...(reviewStatus === 'verified' ? { evidence: {
      bpp: { reportHash: digest('c'), resourceFingerprint: digest('d'), hostClass: 'linux-amd64', repetitions: 20, caseCount: 10, maxCpuMs: 800, maxWallMs: 900, peakMemoryBytes: 128 * 1024 ** 2, safetyMarginReason: 'measured headroom' },
      python: { reportHash: digest('e'), resourceFingerprint: digest('f'), hostClass: 'linux-amd64', repetitions: 20, caseCount: 10, maxCpuMs: 1200, maxWallMs: 1300, peakMemoryBytes: 128 * 1024 ** 2, safetyMarginReason: 'measured headroom' },
    } } : {}),
    preparationCleanupMs: 5000,
  };
}

function ImportHarness() {
  const [current, setCurrent] = useState<JudgePolicy | null>(null);
  return <JudgePolicyEditor policy={current} onReplace={setCurrent} />;
}

it('keeps label targets unique when multiple contest problems have policy editors', () => {
  render(<><JudgePolicyEditor onReplace={vi.fn()} /><JudgePolicyEditor onReplace={vi.fn()} /></>);
  const inputs = screen.getAllByLabelText('정책 JSON 가져오기');
  expect(inputs).toHaveLength(2);
  expect(inputs[0].id).not.toBe(inputs[1].id);
});

describe('JudgePolicyEditor', () => {
  it('preserves the exact supervisor fingerprint from an imported policy', () => {
    const body = policy();
    body.profiles.python!.launcherDigest = digest('1');
    expect(parseImportedJudgePolicy(JSON.stringify(body)).profiles.python!.launcherDigest).toBe(digest('1'));
    body.profiles.python!.launcherDigest = 'latest';
    expect(() => parseImportedJudgePolicy(JSON.stringify(body))).toThrow();
  });

  it('allows unpinned drafts without inventing a supervisor fingerprint', () => {
    const body = policy('draft');
    expect(parseImportedJudgePolicy(JSON.stringify(body)).profiles.python!.launcherDigest).toBeUndefined();
    body.profiles.python!.launcherDigest = null;
    expect(parseImportedJudgePolicy(JSON.stringify(body)).profiles.python!.launcherDigest).toBeNull();
  });

  it('reviews imported runtime limits and verified measurement evidence without a browser verify action', () => {
    render(<JudgePolicyEditor policy={policy()} onReplace={() => {}} />);

    expect(screen.getByText('검증됨')).toBeInTheDocument();
    expect(screen.getByText('CPython 3.13')).toBeInTheDocument();
    expect(screen.getAllByText('CPU 2.75초 · Wall 3초 · 메모리 256 MiB')).not.toHaveLength(0);
    expect(screen.getByRole('table', { name: '가져온 언어별 채점 정책' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /검증/ })).not.toBeInTheDocument();
  });

  it('replaces the policy only after a valid explicit JSON import and explains draft status', async () => {
    const user = userEvent.setup();
    render(<ImportHarness />);

    fireEvent.change(screen.getByRole('textbox', { name: '정책 JSON 가져오기' }), { target: { value: JSON.stringify(policy('draft')) } });
    await user.click(screen.getByRole('button', { name: '정책 JSON 확인 후 교체' }));

    expect(screen.getByText('초안')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('초안 정책은 대회 초안에만 저장할 수 있으며');
    expect(screen.getByText('CPython 3.13')).toBeInTheDocument();
  });

  it('surfaces JSON/model validation failures and leaves the existing policy unchanged', async () => {
    const user = userEvent.setup();
    const replace = vi.fn();
    const { rerender } = render(<JudgePolicyEditor policy={policy()} onReplace={replace} />);

    fireEvent.change(screen.getByRole('textbox', { name: '정책 JSON 가져오기' }), { target: { value: '{not-json' } });
    await user.click(screen.getByRole('button', { name: '정책 JSON 확인 후 교체' }));
    expect(screen.getByRole('alert')).toHaveTextContent('정책 JSON 형식이 올바르지 않습니다');
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByText('검증됨')).toBeInTheDocument();

    rerender(<JudgePolicyEditor policy={null} onReplace={replace} />);
    const missingEvidence = { ...policy(), evidence: {} };
    fireEvent.change(screen.getByRole('textbox', { name: '정책 JSON 가져오기' }), { target: { value: JSON.stringify(missingEvidence) } });
    await user.click(screen.getByRole('button', { name: '정책 JSON 확인 후 교체' }));
    expect(screen.getByRole('alert')).toHaveTextContent('검증 정책에는 모든 런타임 언어의 측정 증거가 필요합니다.');
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('가져온 정책이 없습니다.');
  });
});
