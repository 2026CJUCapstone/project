import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';
import type { CompilerLanguage } from './compilerApi';
import { getAuthOwner } from './authIdentity';

export interface CodeProject {
  id: string;
  revision: string;
  scope: string;
  title: string;
  language: CompilerLanguage;
  code: string;
  createdAt: string;
  updatedAt: string;
}

const revisions = new Map<string, string | null>();
const revisionKey = (scope: string, owner: string) => `b-compiler-project-revision:${encodeURIComponent(owner)}:${encodeURIComponent(scope)}`;

export function getProjectBaseRevision(scope: string, owner: string): string | null {
  const key = revisionKey(scope, owner);
  if (!revisions.has(key)) revisions.set(key, localStorage.getItem(key));
  return revisions.get(key) ?? null;
}

export function acceptProjectRevision(scope: string, owner: string, revision: string | null) {
  const key = revisionKey(scope, owner);
  revisions.set(key, revision);
  try {
    if (revision === null) localStorage.removeItem(key);
    else localStorage.setItem(key, revision);
  } catch {
    // A storage quota failure must not turn a successful CAS into a failed save.
  }
}

export async function getCodeProject(scope: string, expectedOwner = getAuthOwner()): Promise<CodeProject | null> {
  if (!expectedOwner.startsWith('account:') || expectedOwner !== getAuthOwner()) return null;
  const response = await fetch(`${API_BASE_URL}/api/v1/projects/${encodeURIComponent(scope)}`, {
    headers: { Accept: 'application/json', ...getAuthHeaders() },
  });
  if (expectedOwner !== getAuthOwner()) return null;
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw await parseApiError(response, '저장된 코드를 불러오지 못했습니다.');
  }
  const project = (await response.json()) as CodeProject;
  return expectedOwner === getAuthOwner() ? project : null;
}

export async function saveCodeProject(
  scope: string,
  payload: { code: string; language: CompilerLanguage; title: string },
  expectedOwner = getAuthOwner(),
): Promise<CodeProject | null> {
  if (!expectedOwner.startsWith('account:') || expectedOwner !== getAuthOwner()) return null;
  const token = typeof window !== 'undefined' ? window.localStorage.getItem('authToken') : null;
  if (!token) return null;

  const response = await fetch(`${API_BASE_URL}/api/v1/projects/${encodeURIComponent(scope)}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ ...payload, expectedRevision: getProjectBaseRevision(scope, expectedOwner) }),
  });
  if (response.status === 401 || response.status === 403) {
    throw await parseApiError(response, '로그인 세션이 만료되었습니다.');
  }
  if (!response.ok) {
    if (response.status === 409 && expectedOwner === getAuthOwner()) {
      window.dispatchEvent(new CustomEvent('project-save-conflict', { detail: { scope, owner: expectedOwner } }));
    }
    throw await parseApiError(response, '코드 저장에 실패했습니다.');
  }
  const saved = (await response.json()) as CodeProject;
  acceptProjectRevision(scope, expectedOwner, saved.revision);
  return saved;
}
