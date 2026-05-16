function normalizeApiBaseUrl(value: string): string {
  if (!value || value === '/') return '';
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

const apiBaseFromBaseUrl = import.meta.env.BASE_URL === '/' ? '' : import.meta.env.BASE_URL.replace(/\/$/, '');
const API_BASE_URL = normalizeApiBaseUrl(import.meta.env.VITE_API_URL || apiBaseFromBaseUrl);

export interface LoginResponse {
  accessToken: string;
  tokenType: string;
}

interface BackendTokenResponse {
  access_token: string;
  token_type: string;
}

async function request<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail || '인증 요청에 실패했습니다.');
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
