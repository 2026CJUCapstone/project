import { describe, expect, it } from 'vitest';
import { ApiError, parseApiError } from './apiBase';

describe('parseApiError', () => {
  it('preserves the HTTP status while keeping the API detail', async () => {
    const error = await parseApiError({
      status: 503,
      json: async () => ({ detail: 'temporarily unavailable' }),
    } as Response, 'request failed');

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(503);
    expect(error.message).toBe('temporarily unavailable');
  });
});
