import { API_BASE_URL, getAuthHeaders, parseApiError } from './apiBase';
import type { AuthUser } from './authApi';

export type AdminUser = AuthUser;

export interface AdminUsersResponse {
  users: AdminUser[];
  total: number;
  filteredTotal: number;
}

export async function getAdminUsers(options: { limit?: number; offset?: number; search?: string } = {}): Promise<AdminUsersResponse> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 100),
    offset: String(options.offset ?? 0),
  });
  if (options.search?.trim()) params.set('search', options.search.trim());
  const response = await fetch(`${API_BASE_URL}/api/v1/admin/users?${params.toString()}`, {
    headers: { Accept: 'application/json', ...getAuthHeaders() },
  });
  if (!response.ok) {
    throw await parseApiError(response, '사용자 목록을 불러오지 못했습니다.');
  }
  return (await response.json()) as AdminUsersResponse;
}

export async function updateAdminUser(
  userId: string,
  payload: { role?: 'user' | 'admin'; nickname?: string | null; avatarUrl?: string | null },
): Promise<AdminUser> {
  const response = await fetch(`${API_BASE_URL}/api/v1/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await parseApiError(response, '사용자 정보 저장에 실패했습니다.');
  }
  return (await response.json()) as AdminUser;
}
