import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { publishProblem } from './problemApi';

const { getAuthHeadersMock, parseApiErrorMock } = vi.hoisted(() => ({
  getAuthHeadersMock: vi.fn(),
  parseApiErrorMock: vi.fn(),
}));

vi.mock('./apiBase', () => ({
  API_BASE_URL: 'https://api.example.test',
  getAuthHeaders: getAuthHeadersMock,
  parseApiError: parseApiErrorMock,
}));

describe('problem publication API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: vi.fn().mockResolvedValue({ id: 'problem/one', publicationStatus: 'published' }) }));
    getAuthHeadersMock.mockReset().mockReturnValue({ Authorization: 'Bearer admin-token' });
    parseApiErrorMock.mockReset();
  });

  afterEach(() => vi.unstubAllGlobals());

  it('POSTs the encoded problem ID to the explicit publish gate with admin auth', async () => {
    await expect(publishProblem('problem/one & two')).resolves.toEqual({ id: 'problem/one', publicationStatus: 'published' });

    expect(fetch).toHaveBeenCalledWith('https://api.example.test/api/v1/problems/problem%2Fone%20%26%20two/publish', {
      method: 'POST',
      headers: { Authorization: 'Bearer admin-token' },
    });
  });

  it('preserves server publication-gate errors', async () => {
    const response = { ok: false, status: 409 };
    const gateError = new Error('검수 승인 후 공개할 수 있습니다.');
    vi.mocked(fetch).mockResolvedValue(response as Response);
    parseApiErrorMock.mockResolvedValue(gateError);

    await expect(publishProblem('problem-1')).rejects.toBe(gateError);
    expect(parseApiErrorMock).toHaveBeenCalledWith(response, '문제 공개에 실패했습니다.');
  });
});
