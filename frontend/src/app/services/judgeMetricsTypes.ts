/**
 * Immutable aggregate measurements published with a completed submission.
 * These are cgroup-v2 whole-phase measurements, not per-test-case traces.
 */
export interface JudgeResourceUsageStage {
  cpuMs: number;
  wallMs: number;
  peakMemoryBytes: number;
}

export interface JudgeRunResourceUsage extends JudgeResourceUsageStage {
  /** Total CPU time across every executed case. */
  cpuMs: number;
  /** Total wall-clock time across every executed case. */
  wallMs: number;
  /** Largest CPU time from a single executed case. */
  maxCpuMs: number;
  /** Largest wall-clock time from a single executed case. */
  maxWallMs: number;
}

export interface JudgeResourceUsage {
  version: 1;
  measurement: 'cgroup-v2-whole-phase';
  policyId: string;
  policyRevision: number;
  compile: JudgeResourceUsageStage;
  run: JudgeRunResourceUsage | null;
}
