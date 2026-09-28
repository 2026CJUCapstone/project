import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';

export const AUTHORING_CATEGORIES = ['sources', 'statement', 'tests', 'resources'] as const;
export const AUTHORING_LANGUAGES = ['bpp', 'c', 'cpp', 'python', 'java', 'javascript'] as const;

export type AuthoringCategory = typeof AUTHORING_CATEGORIES[number];
export type AuthoringDecision = 'pending' | 'approved' | 'rejected';
export type AuthoringLanguage = typeof AUTHORING_LANGUAGES[number];
export type ReuseBasis = 'pending' | 'license' | 'permission' | 'original';
export type AssetRole = 'reference' | 'validator' | 'generator' | 'wrong_solution' | 'proof' | 'measurement';

export interface SourceReference {
  url: string;
  title: string;
  author?: string;
  event?: string;
  reuseBasis?: ReuseBasis;
  reuseEvidence?: string;
  externalTier?: string | null;
  tierCheckedAt?: string | null;
}

export interface AssetReference {
  role: AssetRole;
  name: string;
  digest: string;
  language?: AuthoringLanguage | null;
}

/**
 * This is intentionally the server's wire shape.  The raw editor validates it,
 * but does not add omitted optional fields or otherwise rewrite the metadata.
 */
export interface AuthoringMetadata {
  sources: SourceReference[];
  adaptationNotes: string;
  assets?: AssetReference[];
  requiredLanguages: AuthoringLanguage[];
}

export interface ProblemAuthoringEvent {
  id: string;
  actorId: string;
  fingerprint: string;
  category: AuthoringCategory;
  decision: Exclude<AuthoringDecision, 'pending'>;
  note: string;
  sequence: number;
  createdAt: string;
}

export interface ProblemAuthoringRecord {
  problemId: string;
  fingerprint: string;
  metadata: AuthoringMetadata | null;
  categories: Record<AuthoringCategory, AuthoringDecision>;
  events: ProblemAuthoringEvent[];
}

export interface MetadataUpdate {
  expectedFingerprint: string;
  metadata: AuthoringMetadata;
}

export interface AuthoringReviewWrite {
  requestId: string;
  expectedFingerprint: string;
  category: AuthoringCategory;
  decision: Exclude<AuthoringDecision, 'pending'>;
  note: string;
}

async function authoringRequest<T>(problemId: string, path = '', method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api/v1/problems/${encodeURIComponent(problemId)}/authoring${path}`, {
    method,
    signal,
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await parseApiError(response, '출처·검수 정보를 처리하지 못했습니다.');
  return await response.json() as T;
}

export function getProblemAuthoring(problemId: string, signal?: AbortSignal): Promise<ProblemAuthoringRecord> {
  return authoringRequest<ProblemAuthoringRecord>(problemId, '', 'GET', undefined, signal);
}

export function updateProblemAuthoring(problemId: string, body: MetadataUpdate, signal?: AbortSignal): Promise<ProblemAuthoringRecord> {
  return authoringRequest<ProblemAuthoringRecord>(problemId, '', 'PUT', body, signal);
}

export function appendProblemAuthoringReview(problemId: string, body: AuthoringReviewWrite, signal?: AbortSignal): Promise<ProblemAuthoringRecord> {
  return authoringRequest<ProblemAuthoringRecord>(problemId, '/reviews', 'POST', body, signal);
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function assertKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const unexpected = Object.keys(value).filter(key => !allowed.includes(key));
  if (unexpected.length) throw new Error(`${label}에 허용되지 않은 필드가 있습니다: ${unexpected.join(', ')}`);
}

function requiredString(value: unknown, label: string, maximum: number): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label}은(는) 비어 있지 않은 문자열이어야 합니다.`);
  if (value.length > maximum) throw new Error(`${label}은(는) ${maximum.toLocaleString('ko-KR')}자까지 입력할 수 있습니다.`);
  return value;
}

function optionalString(value: unknown, label: string, maximum: number): void {
  if (value !== undefined && (typeof value !== 'string' || value.length > maximum)) {
    throw new Error(`${label}의 형식 또는 길이가 올바르지 않습니다.`);
  }
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch {
    return false;
  }
}

function assertSource(value: unknown, index: number): asserts value is SourceReference {
  const label = `sources[${index}]`;
  if (!isPlainRecord(value)) throw new Error(`${label}은(는) 객체여야 합니다.`);
  assertKeys(value, ['url', 'title', 'author', 'event', 'reuseBasis', 'reuseEvidence', 'externalTier', 'tierCheckedAt'], label);
  const url = requiredString(value.url, `${label}.url`, 2_000);
  if (!isHttpUrl(url)) throw new Error(`${label}.url은 http 또는 https URL이어야 합니다.`);
  requiredString(value.title, `${label}.title`, 300);
  optionalString(value.author, `${label}.author`, 300);
  optionalString(value.event, `${label}.event`, 300);
  optionalString(value.reuseEvidence, `${label}.reuseEvidence`, 4_000);
  if (value.reuseBasis !== undefined && !['pending', 'license', 'permission', 'original'].includes(value.reuseBasis as string)) {
    throw new Error(`${label}.reuseBasis 값이 올바르지 않습니다.`);
  }
  if (value.externalTier !== undefined && value.externalTier !== null && (typeof value.externalTier !== 'string' || value.externalTier.length > 80)) {
    throw new Error(`${label}.externalTier의 형식 또는 길이가 올바르지 않습니다.`);
  }
  if (value.tierCheckedAt !== undefined && value.tierCheckedAt !== null && typeof value.tierCheckedAt !== 'string') {
    throw new Error(`${label}.tierCheckedAt은 ISO 시각 문자열 또는 null이어야 합니다.`);
  }
}

function assertAsset(value: unknown, index: number): asserts value is AssetReference {
  const label = `assets[${index}]`;
  if (!isPlainRecord(value)) throw new Error(`${label}은(는) 객체여야 합니다.`);
  assertKeys(value, ['role', 'name', 'digest', 'language'], label);
  if (!['reference', 'validator', 'generator', 'wrong_solution', 'proof', 'measurement'].includes(value.role as string)) {
    throw new Error(`${label}.role 값이 올바르지 않습니다.`);
  }
  requiredString(value.name, `${label}.name`, 240);
  const digest = requiredString(value.digest, `${label}.digest`, 80);
  if (!/^sha256:[0-9a-f]{64}$/.test(digest)) throw new Error(`${label}.digest는 sha256 지문이어야 합니다.`);
  if (value.language !== undefined && value.language !== null && !AUTHORING_LANGUAGES.includes(value.language as AuthoringLanguage)) {
    throw new Error(`${label}.language 값이 올바르지 않습니다.`);
  }
}

/** Parses exact wire JSON; it never supplies missing fields or changes category state. */
export function parseAuthoringMetadata(raw: string): AuthoringMetadata {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error('출처 메타데이터 JSON 형식이 올바르지 않습니다.');
  }
  if (!isPlainRecord(parsed)) throw new Error('출처 메타데이터는 JSON 객체여야 합니다.');
  assertKeys(parsed, ['sources', 'adaptationNotes', 'assets', 'requiredLanguages'], '메타데이터');
  if (!Array.isArray(parsed.sources) || parsed.sources.length < 1 || parsed.sources.length > 20) {
    throw new Error('sources는 1개 이상 20개 이하의 목록이어야 합니다.');
  }
  parsed.sources.forEach(assertSource);
  requiredString(parsed.adaptationNotes, 'adaptationNotes', 10_000);
  if (!Array.isArray(parsed.requiredLanguages) || parsed.requiredLanguages.length < 1 || parsed.requiredLanguages.length > 6) {
    throw new Error('requiredLanguages는 1개 이상 6개 이하의 목록이어야 합니다.');
  }
  if (parsed.requiredLanguages.some(language => !AUTHORING_LANGUAGES.includes(language as AuthoringLanguage))
    || new Set(parsed.requiredLanguages).size !== parsed.requiredLanguages.length) {
    throw new Error('requiredLanguages 값은 중복 없는 지원 언어여야 합니다.');
  }
  if (parsed.assets !== undefined) {
    if (!Array.isArray(parsed.assets) || parsed.assets.length > 120) throw new Error('assets는 최대 120개인 목록이어야 합니다.');
    parsed.assets.forEach(assertAsset);
  }
  return parsed as unknown as AuthoringMetadata;
}

export function safeHttpUrl(value: string): string | null {
  return isHttpUrl(value) ? value : null;
}
