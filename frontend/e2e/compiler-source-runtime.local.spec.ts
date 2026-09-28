import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { mapCompileSource } from '../src/app/services/sourceMapping';
import { pipelineItems } from '../src/app/services/pipelineLineage';

// Opt-in only: submits two tiny guest compile jobs, never contest submissions.
test('real Bpp byte ranges map to the exact Unicode source snapshot', async ({ request }, testInfo) => {
  const base = process.env.GRAPH_RUNTIME_BASE_URL;
  test.skip(!base, 'Set GRAPH_RUNTIME_BASE_URL explicitly for a bounded runtime check.');
  test.setTimeout(120000);
  const reports = [];
  for (const [newline, optimize] of [['\n', false], ['\r\n', true]] as const) {
    const source = ['import emitln from std.io;', '// 한글 😀', 'func main() -> u64 {', '    emitln("안녕 😀");', '    return 0;', '}', ''].join(newline);
    const accepted = await request.post(`${base}/api/v1/executions`, {
      headers: { 'X-Request-ID': randomUUID() },
      data: { source_code: source, language: 'bpp', optimize, target: 'all', kind: 'compile' },
    });
    expect(accepted.status()).toBe(202);
    const receipt = await accepted.json();
    let value: any;
    await expect.poll(async () => {
      const response = await request.get(`${base}/api/v1/executions/${receipt.id}`);
      expect(response.ok()).toBe(true);
      const job = await response.json();
      if (job.status === 'failed') throw new Error(job.result?.error ?? 'Compiler job failed');
      value = job.result?.value;
      return job.status;
    }, { timeout: 55000, intervals: [750, 1000, 2000] }).toBe('completed');
    expect(value?.success, JSON.stringify(value?.errors)).toBe(true);
    expect(value.metadata?.source_range_semantics?.offsetEncoding).toBe('byte');
    const normalized = mapCompileSource({ ...value, executionTime: value.execution_time,
      metadata: { sourceRangeSemantics: value.metadata.source_range_semantics } }, source)!;
    const items = pipelineItems(normalized);
    const mapped = items.flatMap(item => item.ranges.map(range => ({
      stage: item.stage, text: source.slice(range.startOffset!, range.endOffset!),
      line: range.startLine, column: range.startColumn,
    })));
    for (const stage of ['AST', 'SSA', 'IR', 'ASM']) {
      const ranges = mapped.filter(item => item.stage === stage);
      expect(ranges.length, `${stage} mapped ranges`).toBeGreaterThan(0);
      expect(ranges.some(item => item.text.includes('return 0') || item.text.includes('emitln("안녕')), `${stage} semantic source link`).toBe(true);
    }
    expect(mapped.some(item => item.line === 4 && item.column === 5 && item.text.includes('emitln'))).toBe(true);
    reports.push({ newline: JSON.stringify(newline), optimize, mappedRanges: mapped.length,
      stages: Object.fromEntries(['AST', 'SSA', 'IR', 'ASM'].map(stage => [stage, mapped.filter(item => item.stage === stage).length])) });
  }
  await testInfo.attach('runtime-mapping-summary', { body: JSON.stringify(reports, null, 2), contentType: 'application/json' });
});
