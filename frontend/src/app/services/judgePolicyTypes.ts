export const JUDGE_POLICY_LANGUAGES = ['bpp', 'c', 'cpp', 'python', 'java', 'javascript'] as const;

export type JudgePolicyLanguage = (typeof JUDGE_POLICY_LANGUAGES)[number];

export interface JudgePolicyStageLimits {
  cpuMs: number;
  wallMs: number;
  memoryBytes: number;
  outputBytes: number;
  pids: number;
  tmpBytes: number;
}

export interface JudgePolicyLanguageLimits {
  runtimeVersion: string;
  compile: JudgePolicyStageLimits;
  run: JudgePolicyStageLimits;
}

/** Public, server-owned limit summary returned by judge_policy.public_limits. */
export interface PublicJudgeLimits {
  policyId: string;
  revision: number;
  reviewStatus: 'draft' | 'verified';
  languages: Partial<Record<JudgePolicyLanguage, JudgePolicyLanguageLimits>>;
}

/** Raw, administrator-only policy imported from the offline measurement workflow. */
export interface JudgePolicyRuntimeLimits {
  runtimeId: string;
  runtimeVersion: string;
  imageDigest: string;
  workerClass: string;
  toolchainProfile: string;
  launcherDigest?: string | null;
  compile: JudgePolicyStageLimits;
  run: JudgePolicyStageLimits;
}

export interface JudgePolicyMeasurementEvidence {
  reportHash: string;
  resourceFingerprint: string;
  hostClass: string;
  repetitions: number;
  caseCount: number;
  maxCpuMs: number;
  maxWallMs: number;
  peakMemoryBytes: number;
  safetyMarginReason: string;
}

/**
 * The editable policy stays intentionally separate from PublicJudgeLimits.
 * It includes runtime identity and measurement evidence, and must originate
 * from the offline measurement workflow rather than browser-generated values.
 */
export interface JudgePolicy {
  schemaVersion: 1;
  policyId: string;
  revision: number;
  reviewStatus: 'draft' | 'verified';
  testSuiteHash: string;
  profiles: Partial<Record<JudgePolicyLanguage, JudgePolicyRuntimeLimits>>;
  evidence?: Partial<Record<JudgePolicyLanguage, JudgePolicyMeasurementEvidence>>;
  preparationCleanupMs: number;
}

type UnknownRecord = Record<string, unknown>;

const POLICY_LANGUAGES = new Set<string>(JUDGE_POLICY_LANGUAGES);
const IDENTIFIER = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;
const DIGEST = /^sha256:[0-9a-f]{64}$/;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: UnknownRecord, keys: readonly string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function isIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= 80 && IDENTIFIER.test(value);
}

function isDigest(value: unknown): value is string {
  return typeof value === 'string' && DIGEST.test(value);
}

function isIntegerInRange(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max;
}

function isText(value: unknown, min = 1, max = 2000): value is string {
  return typeof value === 'string' && value.length >= min && value.length <= max;
}

function isStageLimits(value: unknown): value is JudgePolicyStageLimits {
  if (!isRecord(value) || !hasOnlyKeys(value, ['cpuMs', 'wallMs', 'memoryBytes', 'outputBytes', 'pids', 'tmpBytes'])) return false;
  return isIntegerInRange(value.cpuMs, 1, 300_000)
    && isIntegerInRange(value.wallMs, 1, 600_000)
    && isIntegerInRange(value.memoryBytes, 1_048_576, 8 * 1024 ** 3)
    && isIntegerInRange(value.outputBytes, 1, 16 * 1024 ** 2)
    && isIntegerInRange(value.pids, 1, 256)
    && isIntegerInRange(value.tmpBytes, 0, 8 * 1024 ** 3)
    && value.tmpBytes <= value.memoryBytes;
}

function isRuntimeLimits(value: unknown): value is JudgePolicyRuntimeLimits {
  if (!isRecord(value) || !hasOnlyKeys(value, ['runtimeId', 'runtimeVersion', 'imageDigest', 'workerClass', 'toolchainProfile', 'launcherDigest', 'compile', 'run'])) return false;
  return isIdentifier(value.runtimeId)
    && isText(value.runtimeVersion, 1, 160)
    && isDigest(value.imageDigest)
    && isIdentifier(value.workerClass)
    && isIdentifier(value.toolchainProfile)
    && (value.launcherDigest === undefined || value.launcherDigest === null || isDigest(value.launcherDigest))
    && isStageLimits(value.compile)
    && isStageLimits(value.run);
}

function isEvidence(value: unknown): value is JudgePolicyMeasurementEvidence {
  if (!isRecord(value) || !hasOnlyKeys(value, ['reportHash', 'resourceFingerprint', 'hostClass', 'repetitions', 'caseCount', 'maxCpuMs', 'maxWallMs', 'peakMemoryBytes', 'safetyMarginReason'])) return false;
  return isDigest(value.reportHash)
    && isDigest(value.resourceFingerprint)
    && isIdentifier(value.hostClass)
    && isIntegerInRange(value.repetitions, 10, 100_000)
    && isIntegerInRange(value.caseCount, 1, 200)
    && isIntegerInRange(value.maxCpuMs, 0, 300_000)
    && isIntegerInRange(value.maxWallMs, 0, 600_000)
    && isIntegerInRange(value.peakMemoryBytes, 0, 8 * 1024 ** 3)
    && isText(value.safetyMarginReason);
}

/**
 * Validate an explicitly imported raw policy without adding or inferring any
 * field. The API remains the authoritative validator before persistence.
 */
export function parseImportedJudgePolicy(raw: string): JudgePolicy {
  let candidate: unknown;
  try {
    candidate = JSON.parse(raw);
  } catch {
    throw new Error('정책 JSON 형식이 올바르지 않습니다. 오프라인 측정 결과를 그대로 붙여 넣으세요.');
  }
  if (!isRecord(candidate) || !hasOnlyKeys(candidate, ['schemaVersion', 'policyId', 'revision', 'reviewStatus', 'testSuiteHash', 'profiles', 'evidence', 'preparationCleanupMs'])) {
    throw new Error('정책 필드가 현재 측정 정책 모델과 일치하지 않습니다.');
  }
  if (candidate.schemaVersion !== 1 || !isIdentifier(candidate.policyId)
    || !isIntegerInRange(candidate.revision, 1, Number.MAX_SAFE_INTEGER)
    || (candidate.reviewStatus !== 'draft' && candidate.reviewStatus !== 'verified')
    || !isDigest(candidate.testSuiteHash)
    || !isIntegerInRange(candidate.preparationCleanupMs, 1000, 120_000)
    || !isRecord(candidate.profiles)) {
    throw new Error('정책의 버전, 식별자, 테스트 fingerprint 또는 준비 정리 시간이 올바르지 않습니다.');
  }

  const profileEntries = Object.entries(candidate.profiles);
  if (profileEntries.length < 1 || profileEntries.length > JUDGE_POLICY_LANGUAGES.length
    || profileEntries.some(([language, profile]) => !POLICY_LANGUAGES.has(language) || !isRuntimeLimits(profile))) {
    throw new Error('언어별 런타임과 컴파일·실행 제한이 측정 정책 모델과 일치하지 않습니다.');
  }

  const evidence = candidate.evidence;
  if (evidence !== undefined && !isRecord(evidence)) {
    throw new Error('측정 증거 형식이 올바르지 않습니다.');
  }
  const evidenceEntries = evidence ? Object.entries(evidence) : [];
  if (evidenceEntries.some(([language, value]) => !Object.prototype.hasOwnProperty.call(candidate.profiles, language) || !isEvidence(value))) {
    throw new Error('측정 증거는 등록한 런타임 언어에 대해서만 완전한 형태로 제공해야 합니다.');
  }
  if (candidate.reviewStatus === 'verified' && evidenceEntries.length !== profileEntries.length) {
    throw new Error('검증 정책에는 모든 런타임 언어의 측정 증거가 필요합니다.');
  }
  for (const [language, value] of evidenceEntries) {
    const profile = candidate.profiles[language] as JudgePolicyRuntimeLimits;
    const measurement = value as JudgePolicyMeasurementEvidence;
    if (measurement.hostClass !== profile.workerClass
      || measurement.maxCpuMs >= profile.run.cpuMs
      || measurement.maxWallMs >= profile.run.wallMs
      || measurement.peakMemoryBytes >= profile.run.memoryBytes) {
      throw new Error(`${language} 측정 증거는 같은 worker class에서 실행 제한보다 여유가 있어야 합니다.`);
    }
  }

  return candidate as unknown as JudgePolicy;
}
