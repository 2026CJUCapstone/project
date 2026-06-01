import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';

export interface LoginResponse {
  accessToken: string;
  tokenType: string;
}

interface BackendTokenResponse {
  access_token: string;
  token_type: string;
}

export interface AuthUser {
  id: string;
  username: string;
  nickname?: string | null;
  totalScore: number;
  avatarUrl?: string | null;
  role: 'user' | 'admin' | string;
}

async function request<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw await parseApiError(response, '인증 요청에 실패했습니다.');
  }

  return (await response.json()) as T;
}

export async function register(username: string, password: string, nickname?: string): Promise<void> {
  await request('/api/v1/auth/register', { username, password, nickname: nickname || undefined });
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const result = await request<BackendTokenResponse>('/api/v1/auth/login', { username, password });
  return {
    accessToken: result.access_token,
    tokenType: result.token_type,
  };
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: { Accept: 'application/json', ...getAuthHeaders() },
  });
  if (!response.ok) {
    throw await parseApiError(response, '로그인 정보를 불러오지 못했습니다.');
  }
  return (await response.json()) as AuthUser;
}

export async function updateProfile(payload: {
  nickname?: string | null;
  avatarUrl?: string | null;
}): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/profile`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await parseApiError(response, '프로필 저장에 실패했습니다.');
  }
  return (await response.json()) as AuthUser;
}
