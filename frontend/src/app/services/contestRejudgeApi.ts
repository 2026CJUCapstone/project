import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';
import type { JudgePolicy } from './judgePolicyTypes';
import type { HiddenTestCase, Sha256Digest, TestCase } from './problemApi';
import type { AuthoringCategory, AuthoringDecision, AuthoringMetadata } from './problemAuthoringApi';

export type ContestRejudgeStatus = 'pending' | 'running' | 'ready' | 'failed' | 'cancelled' | 'applied';

export interface ContestRejudgeBatch {
  id: string;
  contestProblemId: string;
  actorId: string;
  reason: string;
  revision: number;
  status: ContestRejudgeStatus;
  createdAt: string;
  finishedAt: string | null;
  total: number;
  completed: number;
  changed: number;
  failed: number;
  /** Absent only while reading a pre-v21 server response. */
  shardCount?: number;
  completedShards?: number;
}

export interface ContestRejudgeItem {
  id: string;
  submissionId: string;
  /** Zero is the compatibility projection for a pre-v21 candidate. */
  shardSequence?: number;
  language: string;
  receivedAt: string;
  status: string;
  beforeVerdict: string | null;
  afterVerdict: string | null;
  finishedAt: string | null;
}

/** A server-owned contest snapshot; unknown metadata must remain untouched. */
export interface ContestRejudgeSnapshot {
  sample: TestCase[];
  hidden: HiddenTestCase[];
  /** Legacy or unreviewed snapshots may not contain an importable JudgePolicy. */
  judgePolicy: unknown;
  [metadata: string]: unknown;
}

export interface ContestRejudgeContext {
  contestProblemId: string;
  snapshotHash: Sha256Digest;
  snapshot: ContestRejudgeSnapshot;
}

export interface ContestRejudgeCreateRequest {
  requestId: string;
  contestProblemId: string;
  expectedSnapshotHash: Sha256Digest;
  reason: string;
  sample: TestCase[];
  hidden: HiddenTestCase[];
  judgePolicy: JudgePolicy;
  /** Omission retains the frozen metadata; callers may never clear it with null. */
  authoring?: AuthoringMetadata;
}

export interface ContestRejudgeDiscardRequest {
  expectedRequestHash: Sha256Digest;
}

export interface ContestRejudgeApplyRequest extends ContestRejudgeDiscardRequest {
  expectedScoreboardRevision: number;
  expectedPreviewHash: Sha256Digest;
  publicNote: string;
}

export interface ContestRejudgeApplication {
  actorId: string;
  appliedAt: string;
  publicNote: string;
  beforeRevision: number;
  afterRevision: number;
  legacyResolutionProvenance: Record<string, unknown> | null;
}

export interface ContestRejudgeReviewEvent {
  id: string;
  actorId: string;
  fingerprint: Sha256Digest;
  category: AuthoringCategory;
  decision: Exclude<AuthoringDecision, 'pending'>;
  note: string;
  sequence: number;
  createdAt: string;
}

export interface ContestRejudgeReviewWrite {
  requestId: string;
  expectedRequestHash: Sha256Digest;
  expectedFingerprint: Sha256Digest;
  category: AuthoringCategory;
  decision: Exclude<AuthoringDecision, 'pending'>;
  note: string;
}

/** Administrator-only correction review, including the frozen private candidate. */
export interface ContestRejudgeReviews {
  batchId: string;
  requestHash: Sha256Digest;
  fingerprint: Sha256Digest;
  metadata: AuthoringMetadata | null;
  categories: Record<AuthoringCategory, AuthoringDecision>;
  events: ContestRejudgeReviewEvent[];
  canReview: boolean;
  ready: boolean;
  basis: Record<string, unknown> | null;
  applicationProvenance: Record<string, unknown> | null;
  snapshot: ContestRejudgeSnapshot;
}

export interface ContestRejudgeBatchesResponse {
  batches: ContestRejudgeBatch[];
  total: number;
}

export interface ContestRejudgeBatchDetail extends ContestRejudgeBatch {
  requestHash: Sha256Digest;
  beforeScoreboardRevision: number;
  application: ContestRejudgeApplication | null;
  items: ContestRejudgeItem[];
  totalItems: number;
  offset: number;
  limit: number;
}

export interface ContestRejudgePreviewRow {
  userId: string;
  username: string;
  beforeRank: number;
  afterRank: number;
  beforePoints: number;
  afterPoints: number;
  beforePenaltySeconds: number;
  afterPenaltySeconds: number;
  practicePointDelta: number | null;
  blocker: string | null;
}

export interface ContestRejudgePreview {
  previewHash: Sha256Digest;
  requestHash: Sha256Digest;
  beforeScoreboardRevision: number;
  total: number;
  offset: number;
  limit: number;
  blockedCount: number;
  /** Undefined is treated as blocked by callers during mixed-version rollout. */
  reviewBlocked?: boolean;
  rows: ContestRejudgePreviewRow[];
}

export type ContestRejudgeLegacyResolutionDecision = 'retain_unattributed' | 'link_verified_receipt';
export type ContestRejudgeLegacySourceKind = 'practice' | 'contest';

export interface ContestRejudgeLegacyResolutionEvent {
  id: string;
  userId: string;
  problemId: string;
  legacyFingerprint: Sha256Digest;
  decision: ContestRejudgeLegacyResolutionDecision;
  sourceKind: ContestRejudgeLegacySourceKind | null;
  sourceId: string | null;
  sourceFingerprint: Sha256Digest | null;
  actorId: string;
  note: string;
  createdAt: string;
}

export interface ContestRejudgeLegacyCandidate {
  userId: string;
  username: string;
  points: number;
  solvedAt: string;
  legacyFingerprint: Sha256Digest;
  resolution: ContestRejudgeLegacyResolutionEvent | null;
}

export interface ContestRejudgeLegacyResolutions {
  batchId: string;
  requestHash: Sha256Digest;
  candidates: ContestRejudgeLegacyCandidate[];
  resolutions: ContestRejudgeLegacyResolutionEvent[];
}

export interface ContestRejudgeLegacyResolutionWrite {
  requestId: string;
  expectedRequestHash: Sha256Digest;
  userId: string;
  expectedLegacyFingerprint: Sha256Digest;
  decision: ContestRejudgeLegacyResolutionDecision;
  sourceKind?: ContestRejudgeLegacySourceKind;
  sourceId?: string;
  note: string;
}

/** Audit evidence is intentionally rendered only as bounded rank, score, and penalty facts. */
export interface ContestRejudgeAuditBoardRow {
  rank: number;
  totalPoints: number;
  penaltySeconds: number;
  problems: unknown[];
  [field: string]: unknown;
}

export interface ContestRejudgeAuditRow {
  userId: string;
  before: ContestRejudgeAuditBoardRow;
  after: ContestRejudgeAuditBoardRow | null;
  practicePointDelta: number;
}

export interface ContestRejudgeAudit {
  total: number;
  offset: number;
  limit: number;
  beforeRevision: number;
  afterRevision: number;
  rows: ContestRejudgeAuditRow[];
}

function contestPath(contestId: string): string {
  return `${API_BASE_URL}/api/v1/contests/${encodeURIComponent(contestId)}/rejudges`;
}

function pageParams(offset: number, limit: number, maxLimit: number): URLSearchParams {
  return new URLSearchParams({
    offset: String(Math.max(0, Math.floor(offset))),
    limit: String(Math.max(1, Math.min(maxLimit, Math.floor(limit)))),
  });
}

/** One explicit request per action. Rejudge mutations intentionally never retry. */
async function requestJson<T>(
  url: string,
  fallback: string,
  method: 'GET' | 'POST' = 'GET',
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, {
    method,
    signal,
    cache: 'no-store',
    redirect: 'error',
    headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...getAuthHeaders(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await parseApiError(response, fallback);
  return response.json() as Promise<T>;
}

export function getContestRejudgeContext(
  contestId: string,
  contestProblemId: string,
  signal?: AbortSignal,
): Promise<ContestRejudgeContext> {
  const query = new URLSearchParams({ contestProblemId });
  return requestJson<ContestRejudgeContext>(
    `${contestPath(contestId)}/context?${query}`,
    '재채점 컨텍스트를 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

export function createContestRejudge(
  contestId: string,
  request: ContestRejudgeCreateRequest,
  signal?: AbortSignal,
): Promise<ContestRejudgeBatch> {
  return requestJson<ContestRejudgeBatch>(contestPath(contestId), '재채점을 시작하지 못했습니다.', 'POST', request, signal);
}

/** Reads one bounded summary-history page; this endpoint never exposes sources or test data. */
export function getContestRejudgeBatches(
  contestId: string,
  offset = 0,
  limit = 20,
  signal?: AbortSignal,
): Promise<ContestRejudgeBatchesResponse> {
  return requestJson<ContestRejudgeBatchesResponse>(
    `${contestPath(contestId)}?${pageParams(offset, limit, 50)}`,
    '재채점 이력을 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

/** Reads a bounded page of staged per-submission results for one batch. */
export function getContestRejudgeBatch(
  contestId: string,
  batchId: string,
  offset = 0,
  limit = 50,
  signal?: AbortSignal,
): Promise<ContestRejudgeBatchDetail> {
  return requestJson<ContestRejudgeBatchDetail>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}?${pageParams(offset, limit, 100)}`,
    '재채점 상세를 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

export function getContestRejudgePreview(
  contestId: string,
  batchId: string,
  offset = 0,
  limit = 50,
  signal?: AbortSignal,
): Promise<ContestRejudgePreview> {
  return requestJson<ContestRejudgePreview>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/preview?${pageParams(offset, limit, 100)}`,
    '재채점 미리보기를 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

export function getContestRejudgeReviews(
  contestId: string,
  batchId: string,
  signal?: AbortSignal,
): Promise<ContestRejudgeReviews> {
  return requestJson<ContestRejudgeReviews>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/reviews`,
    '정정 검수 기록을 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

/** Reads the bounded list of ambiguous legacy solve awards for an admin review. */
export function getContestRejudgeLegacyResolutions(
  contestId: string,
  batchId: string,
  signal?: AbortSignal,
): Promise<ContestRejudgeLegacyResolutions> {
  return requestJson<ContestRejudgeLegacyResolutions>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/legacy-resolutions`,
    '과거 점수 출처 검수 대상을 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}

/** Appends one explicit legacy-award resolution. Failed mutations are never retried here. */
export function appendContestRejudgeLegacyResolution(
  contestId: string,
  batchId: string,
  request: ContestRejudgeLegacyResolutionWrite,
  signal?: AbortSignal,
): Promise<ContestRejudgeLegacyResolutions> {
  return requestJson<ContestRejudgeLegacyResolutions>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/legacy-resolutions`,
    '과거 점수 출처 검수 결정을 저장하지 못했습니다.',
    'POST',
    request,
    signal,
  );
}

/** One explicit decision only; failed requests deliberately are not retried. */
export function appendContestRejudgeReview(
  contestId: string,
  batchId: string,
  request: ContestRejudgeReviewWrite,
  signal?: AbortSignal,
): Promise<ContestRejudgeReviews> {
  return requestJson<ContestRejudgeReviews>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/reviews`,
    '정정 검수 기록을 저장하지 못했습니다.',
    'POST',
    request,
    signal,
  );
}

export function discardContestRejudge(
  contestId: string,
  batchId: string,
  request: ContestRejudgeDiscardRequest,
  signal?: AbortSignal,
): Promise<ContestRejudgeBatch> {
  return requestJson<ContestRejudgeBatch>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/discard`,
    '재채점 후보를 폐기하지 못했습니다.',
    'POST',
    request,
    signal,
  );
}

export function applyContestRejudge(
  contestId: string,
  batchId: string,
  request: ContestRejudgeApplyRequest,
  signal?: AbortSignal,
): Promise<ContestRejudgeBatch> {
  return requestJson<ContestRejudgeBatch>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/apply`,
    '재채점 결과를 반영하지 못했습니다.',
    'POST',
    request,
    signal,
  );
}

export function getContestRejudgeAudit(
  contestId: string,
  batchId: string,
  offset = 0,
  limit = 50,
  signal?: AbortSignal,
): Promise<ContestRejudgeAudit> {
  return requestJson<ContestRejudgeAudit>(
    `${contestPath(contestId)}/${encodeURIComponent(batchId)}/audit?${pageParams(offset, limit, 100)}`,
    '재채점 감사 기록을 불러오지 못했습니다.',
    'GET',
    undefined,
    signal,
  );
}
