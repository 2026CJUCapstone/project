export function normalizedPageParam(value: string | null, pageSize: number): number {
  const page = Number(value);
  const largestSafePage = Math.floor(Number.MAX_SAFE_INTEGER / pageSize) + 1;

  if (!Number.isSafeInteger(page) || page < 1 || page > largestSafePage) {
    return 1;
  }

  return page;
}
