export type OutputComparisonMode = 'exact' | 'trim-lines';

export interface OutputComparisonResult {
  matches: boolean;
  firstDifferentLine: number | null;
  actualLine: string | null;
  expectedLine: string | null;
}

function normalizeNewlines(value: string): string {
  return value.replace(/\r\n?/g, '\n');
}

function linesForComparison(value: string, mode: OutputComparisonMode): string[] {
  const lines = normalizeNewlines(value)
    .split('\n')
    .map((line) => mode === 'trim-lines' ? line.replace(/[ \t]+$/g, '') : line);

  if (mode === 'trim-lines') {
    while (lines.length > 0 && lines[lines.length - 1] === '') {
      lines.pop();
    }
  }

  return lines;
}

export function compareOutput(
  actual: string,
  expected: string,
  mode: OutputComparisonMode = 'trim-lines',
): OutputComparisonResult {
  const normalizedActual = normalizeNewlines(actual);
  const normalizedExpected = normalizeNewlines(expected);
  const actualLines = linesForComparison(normalizedActual, mode);
  const expectedLines = linesForComparison(normalizedExpected, mode);

  if (mode === 'exact' && normalizedActual === normalizedExpected) {
    return { matches: true, firstDifferentLine: null, actualLine: null, expectedLine: null };
  }

  if (mode === 'trim-lines' && actualLines.length === expectedLines.length && actualLines.every(
    (line, index) => line === expectedLines[index],
  )) {
    return { matches: true, firstDifferentLine: null, actualLine: null, expectedLine: null };
  }

  const firstDifferentIndex = actualLines.findIndex(
    (line, index) => line !== expectedLines[index],
  );
  const differingIndex = firstDifferentIndex >= 0
    ? firstDifferentIndex
    : Math.min(actualLines.length, expectedLines.length);

  return {
    matches: false,
    firstDifferentLine: differingIndex + 1,
    actualLine: actualLines[differingIndex] ?? null,
    expectedLine: expectedLines[differingIndex] ?? null,
  };
}
