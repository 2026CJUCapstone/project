import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';
import type { CompilerLanguage } from './compilerApi';

export interface CodeProject {
  id: string;
  scope: string;
  title: string;
  language: CompilerLanguage;
  code: string;
  createdAt: string;
  updatedAt: string;
}

export async function getCodeProject(scope: string): Promise<CodeProject | null> {
  const response = await fetch(`${API_BASE_URL}/api/v1/projects/${encodeURIComponent(scope)}`, {
    headers: { Accept: 'application/json', ...getAuthHeaders() },
  });
  if (response.status === 401 || response.status === 403 || response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw await parseApiError(response, '저장된 코드를 불러오지 못했습니다.');
  }
  return (await response.json()) as CodeProject;
}

export async function saveCodeProject(
  scope: string,
  payload: { code: string; language: CompilerLanguage; title: string },
): Promise<CodeProject | null> {
  const token = typeof window !== 'undefined' ? window.localStorage.getItem('authToken') : null;
  if (!token) return null;

  const response = await fetch(`${API_BASE_URL}/api/v1/projects/${encodeURIComponent(scope)}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });
  if (response.status === 401 || response.status === 403) {
    return null;
  }
  if (!response.ok) {
    throw await parseApiError(response, '코드 저장에 실패했습니다.');
  }
  return (await response.json()) as CodeProject;
}
