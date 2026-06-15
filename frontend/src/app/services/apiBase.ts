export function normalizeApiBaseUrl(value: string): string {
  if (!value || value === '/') return '';
  return value.endsWith('/') ? value.slice(0, -1) : value;
}

const apiBaseFromBaseUrl =
  import.meta.env.BASE_URL === '/' ? '' : import.meta.env.BASE_URL.replace(/\/$/, '');

export const API_BASE_URL = normalizeApiBaseUrl(
  import.meta.env.VITE_API_URL || apiBaseFromBaseUrl,
);

export function getAuthHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const token = window.localStorage.getItem('authToken');
  if (!token || token === 'undefined' || token === 'null') return {};
  return { Authorization: `Bearer ${token}` };
}

export async function parseApiError(response: Response, fallback: string): Promise<Error> {
  const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
  return new Error(errorData.detail || fallback);
}
