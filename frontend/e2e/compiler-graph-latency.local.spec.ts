import { expect, test, type Locator, type Page, type Request, type Response } from '@playwright/test';
import fs from 'node:fs';

// This suite is intentionally opt-in. It uses the real browser, API and compiler;
// it installs no routes and does not manufacture a compiler response. Generate the
// corpus JSON outside Playwright from runtime/sandbox/verify_bpp_latency.py CASES.
// The source is deliberately never emitted in test output or attachments.
const enabled = process.env.RUN_COMPILER_LATENCY === '1';
const collectOnly = process.env.COMPILER_LATENCY_COLLECT_ONLY === '1';
const strictBudgetMs = 3_000;

type Optimization = 'O0' | 'O1';
type CorpusCase = { name: string; source: string };
type Viewport = { name: string; width: number; height: number };
type RequestSnapshot = {
  startedAtUnixMs: number;
  options: { kind: string | null; language: string | null; optimize: boolean | null; target: string | null };
};
type ResponseSnapshot = {
  endedAtUnixMs: number;
  statusCode: number;
  timing: { startTime: number | null; responseEnd: number | null; responseDurationMs: number | null };
};
type TerminalSnapshot = ResponseSnapshot & {
  executionStatus: 'completed' | 'failed';
  success: boolean | null;
  executionTimeMs: number | null;
};
type ExecutionTrace = { post: RequestSnapshot; executionId?: string; postResponse?: ResponseSnapshot; terminal?: TerminalSnapshot };
type PaintTiming = { clickAtPerformanceMs: number; paintedAtPerformanceMs: number; clickToPaintMs: number };

function positiveInteger(value: string | undefined, fallback: number, name: string): number {
  if (value === undefined || value === '') return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 20) throw new Error(`${name} must be an integer between 1 and 20`);
  return parsed;
}

function loadCorpus(file: string): CorpusCase[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    throw new Error(`Unable to load COMPILER_LATENCY_CORPUS: ${error instanceof Error ? error.message : String(error)}`);
  }
  const entries = Array.isArray(parsed)
    ? parsed.map((entry) => [typeof entry === 'object' && entry !== null ? (entry as { name?: unknown }).name : undefined,
      typeof entry === 'object' && entry !== null ? (entry as { source?: unknown }).source : undefined] as const)
    : typeof parsed === 'object' && parsed !== null ? Object.entries(parsed) : [];
  if (!entries.length) throw new Error('COMPILER_LATENCY_CORPUS must contain at least one case');
  return entries.map(([name, source]) => {
    if (typeof name !== 'string' || !/^[a-zA-Z0-9_-]{1,80}$/.test(name) || typeof source !== 'string' || !source.trim()) {
      throw new Error('COMPILER_LATENCY_CORPUS entries must be named non-empty B++ sources (names use letters, digits, _ or -)');
    }
    return { name, source };
  });
}

function parseOptimizations(value: string | undefined): Optimization[] {
  const values = (value ?? 'O0,O1').split(',').map(item => item.trim().toUpperCase()).filter(Boolean);
  if (!values.length || values.some(item => item !== 'O0' && item !== 'O1')) {
    throw new Error('COMPILER_LATENCY_LEVELS must be a comma-separated subset of O0,O1');
  }
  return [...new Set(values)] as Optimization[];
}

function parseViewports(value: string | undefined): Viewport[] {
  const entries = (value ?? 'desktop:1440x1000,mobile:390x844').split(',').map(item => item.trim()).filter(Boolean);
  if (!entries.length) throw new Error('COMPILER_LATENCY_VIEWPORTS must contain at least one name:WIDTHxHEIGHT entry');
  return entries.map((entry) => {
    const match = /^([a-zA-Z0-9_-]{1,40}):(\d{3,4})x(\d{3,4})$/.exec(entry);
    if (!match) throw new Error(`Invalid COMPILER_LATENCY_VIEWPORTS entry: ${entry}`);
    const [, name, rawWidth, rawHeight] = match;
    const width = Number(rawWidth), height = Number(rawHeight);
    if (width < 320 || width > 3840 || height < 320 || height > 2160) throw new Error(`Viewport out of supported bounds: ${entry}`);
    return { name, width, height };
  });
}

function pathname(request: Request): string {
  return new URL(request.url()).pathname;
}

function isExecutionPost(request: Request): boolean {
  return request.method() === 'POST' && pathname(request).endsWith('/api/v1/executions');
}

function isExecutionStatusRequest(request: Request): boolean {
  return request.method() === 'GET' && /\/api\/v1\/executions\/[^/]+$/.test(pathname(request));
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function responseSnapshot(response: Response): ResponseSnapshot {
  const timing = response.request().timing();
  const startTime = finite(timing.startTime);
  // Playwright reports startTime as an epoch timestamp, but responseEnd is
  // already a duration from that start. A negative responseEnd is unavailable.
  const rawResponseEnd = finite(timing.responseEnd);
  const responseEnd = rawResponseEnd !== null && rawResponseEnd >= 0 ? rawResponseEnd : null;
  return {
    endedAtUnixMs: Date.now(),
    statusCode: response.status(),
    timing: { startTime, responseEnd, responseDurationMs: responseEnd },
  };
}

function requestSnapshot(request: Request): RequestSnapshot {
  let body: unknown = null;
  try { body = request.postDataJSON(); } catch { /* A malformed body cannot be logged. */ }
  const value = typeof body === 'object' && body !== null ? body as Record<string, unknown> : {};
  return {
    startedAtUnixMs: Date.now(),
    options: {
      kind: typeof value.kind === 'string' ? value.kind : null,
      language: typeof value.language === 'string' ? value.language : null,
      optimize: typeof value.optimize === 'boolean' ? value.optimize : null,
      target: typeof value.target === 'string' ? value.target : null,
    },
  };
}

function beginExecutionTracing(page: Page): ExecutionTrace[] {
  const traces: ExecutionTrace[] = [];
  const pendingTerminals = new Map<string, TerminalSnapshot>();
  page.on('request', request => {
    if (isExecutionPost(request)) traces.push({ post: requestSnapshot(request) });
  });
  page.on('response', response => { void captureResponse(response, traces, pendingTerminals); });
  return traces;
}

async function captureResponse(response: Response, traces: ExecutionTrace[], pendingTerminals: Map<string, TerminalSnapshot>): Promise<void> {
  const request = response.request();
  if (isExecutionPost(request)) {
    const trace = [...traces].reverse().find(item => item.postResponse === undefined && item.post.options.optimize !== null);
    if (!trace) return;
    trace.postResponse = responseSnapshot(response);
    const receipt = await response.json().catch(() => null) as { id?: unknown } | null;
    if (typeof receipt?.id === 'string' && receipt.id) {
      trace.executionId = receipt.id;
      const terminal = pendingTerminals.get(receipt.id);
      if (terminal) {
        trace.terminal = terminal;
        pendingTerminals.delete(receipt.id);
      }
    }
    return;
  }
  if (!isExecutionStatusRequest(request)) return;
  const body = await response.json().catch(() => null) as { status?: unknown; result?: { value?: unknown } } | null;
  const executionStatus = body?.status;
  if (executionStatus !== 'completed' && executionStatus !== 'failed') return;
  const value = typeof body?.result?.value === 'object' && body.result.value !== null
    ? body.result.value as { success?: unknown; execution_time?: unknown } : {};
  const terminal: TerminalSnapshot = {
    ...responseSnapshot(response),
    executionStatus,
    success: typeof value.success === 'boolean' ? value.success : null,
    executionTimeMs: finite(value.execution_time),
  };
  const executionId = decodeURIComponent(pathname(request).split('/').pop() ?? '');
  const trace = traces.find(item => item.executionId === executionId);
  if (trace) trace.terminal = terminal;
  else if (executionId) pendingTerminals.set(executionId, terminal);
}

async function preparePage(page: Page, source: string, viewport: Viewport): Promise<void> {
  await page.setViewportSize(viewport);
  await page.addInitScript((initialSource) => {
    localStorage.setItem('b-compiler-editor-code:v2:guest:main', initialSource);
    localStorage.setItem('b-compiler-editor-code-meta:v2:guest:main', JSON.stringify({ language: 'bpp', updatedAt: Date.now() }));
  }, source);
  await page.goto('/ide');
  await expect(page.getByTitle('기본 코드 불러오기')).toBeEnabled();
  await expect(page.locator('.monaco-editor .view-lines')).toContainText('func main');
  if (viewport.width < 768) {
    await page.getByRole('tab', { name: '그래프', exact: true }).click();
    await expect(page.getByRole('tab', { name: '그래프', exact: true })).toHaveAttribute('aria-selected', 'true');
  }
}

async function armPaintMark(button: Locator, clickMark: string, paintedMark: string, selector: string): Promise<void> {
  await button.evaluate((element, { click, painted, target }) => {
    performance.clearMarks(click); performance.clearMarks(painted);
    element.addEventListener('click', () => {
      performance.mark(click);
      const started = performance.now();
      const check = () => {
        const node = document.querySelector(target);
        const bounds = node?.getBoundingClientRect();
        const canvas = node?.closest('.react-flow')?.getBoundingClientRect();
        const left = Math.max(0, canvas?.left ?? 0), top = Math.max(0, canvas?.top ?? 0);
        const right = Math.min(innerWidth, canvas?.right ?? innerWidth), bottom = Math.min(innerHeight, canvas?.bottom ?? innerHeight);
        if (node?.textContent && bounds && bounds.width > 0 && bounds.height > 0 &&
            bounds.right > left && bounds.left < right && bounds.bottom > top && bounds.top < bottom &&
            getComputedStyle(node).opacity !== '0') {
          requestAnimationFrame(() => requestAnimationFrame(() => performance.mark(painted)));
        } else if (performance.now() - started < 30_000) requestAnimationFrame(check);
      };
      requestAnimationFrame(check);
    }, { once: true });
  }, { click: clickMark, painted: paintedMark, target: selector });
}

async function paintTiming(page: Page, clickMark: string, paintedMark: string): Promise<PaintTiming> {
  await page.waitForFunction(({ painted }) => performance.getEntriesByName(painted).length > 0, { painted: paintedMark }, { timeout: 30_000 });
  return page.evaluate(({ click, painted }) => {
    const clickAtPerformanceMs = performance.getEntriesByName(click)[0].startTime;
    const paintedAtPerformanceMs = performance.getEntriesByName(painted)[0].startTime;
    return { clickAtPerformanceMs, paintedAtPerformanceMs, clickToPaintMs: paintedAtPerformanceMs - clickAtPerformanceMs };
  }, { click: clickMark, painted: paintedMark });
}

async function expectTerminal(trace: ExecutionTrace, optimize: boolean): Promise<TerminalSnapshot> {
  await expect.poll(() => trace.terminal !== undefined, { timeout: 30_000 }).toBe(true);
  expect(trace.post.options).toEqual(expect.objectContaining({ kind: 'compile', language: 'bpp', optimize, target: 'all' }));
  expect(trace.postResponse).toBeDefined();
  expect(trace.terminal?.executionStatus).toBe('completed');
  expect(trace.terminal?.success).toBe(true);
  return trace.terminal!;
}

function assertBudget(elapsedMs: number): void {
  if (!collectOnly) expect(elapsedMs).toBeLessThanOrEqual(strictBudgetMs);
}

if (!enabled) {
  test('actual compiler latency is opt-in', async () => {
    test.skip(true, 'Set RUN_COMPILER_LATENCY=1 and COMPILER_LATENCY_CORPUS to an externally generated verifier CASES JSON file');
  });
} else {
  const corpusPath = process.env.COMPILER_LATENCY_CORPUS;
  if (!corpusPath) throw new Error('RUN_COMPILER_LATENCY=1 requires COMPILER_LATENCY_CORPUS; do not load a deploy artifact by default');
  const corpus = loadCorpus(corpusPath);
  const repeats = positiveInteger(process.env.COMPILER_LATENCY_REPEAT, 1, 'COMPILER_LATENCY_REPEAT');
  const optimizations = parseOptimizations(process.env.COMPILER_LATENCY_LEVELS);
  const viewports = parseViewports(process.env.COMPILER_LATENCY_VIEWPORTS);

  for (const sample of corpus) for (const optimization of optimizations) for (const viewport of viewports) for (let repeat = 1; repeat <= repeats; repeat += 1) {
    const mode = collectOnly ? 'collect-only diagnostic' : `strict <=${strictBudgetMs}ms`;
    test(`${sample.name} ${optimization} ${viewport.name} ${viewport.width}x${viewport.height} repeat ${repeat} (${mode})`, async ({ page }, testInfo) => {
      test.setTimeout(45_000);
      const traces = beginExecutionTracing(page);
      await preparePage(page, sample.source, viewport);
      const compile = page.getByTestId('compile-button');
      await expect(compile).toBeEnabled();
      await expect(page.locator('.react-flow__node-ast')).toHaveCount(0);
      const suffix = `${optimization}-${viewport.name}-${repeat}`;
      const clickMark = `compiler-latency-click-${suffix}`;
      const paintedMark = `compiler-latency-painted-${suffix}`;
      let rendered: 'graph' | 'optimization-comparison' = 'graph';

      if (optimization === 'O0') {
        await armPaintMark(compile, clickMark, paintedMark, '.react-flow__node-ast');
        await compile.click();
        await expect(page.locator('.react-flow__node-ast').first()).toBeVisible({ timeout: 30_000 });
      } else {
        // The IDE's normal compile action is intentionally O0. Its real O1 surface is
        // the optimization comparison, which submits the same source with optimize:true.
        // Do not mutate its POST body: that would no longer measure an app request.
        await compile.click();
        await expect(page.locator('.react-flow__node-ast').first()).toBeVisible({ timeout: 30_000 });
        await page.getByRole('button', { name: '최적화 비교', exact: true }).click();
        const compare = page.getByRole('button', { name: '최적화 전후 비교하기', exact: true });
        await expect(compare).toBeEnabled();
        rendered = 'optimization-comparison';
        // The outer comparison region already exists while the request is pending.
        // This child is mounted only after the actual O1 response has been rendered.
        await armPaintMark(compare, clickMark, paintedMark, '[aria-label="함수 단위 최적화 보고"]');
        await compare.click();
        await expect(page.getByRole('region', { name: '최적화 전후 비교' })).toBeVisible({ timeout: 30_000 });
      }

      const targetOptimize = optimization === 'O1';
      await expect.poll(() => traces.some(trace => trace.post.options.optimize === targetOptimize), { timeout: 30_000 }).toBe(true);
      const targetTrace = traces.find(trace => trace.post.options.optimize === targetOptimize)!;
      const terminal = await expectTerminal(targetTrace, targetOptimize);
      const paint = await paintTiming(page, clickMark, paintedMark);
      if (process.env.COMPILER_LATENCY_SCREENSHOTS === '1' && repeat === 1) {
        const screenshot = testInfo.outputPath('actual-graph.png');
        await page.screenshot({ path: screenshot });
        await testInfo.attach('actual-graph', { path: screenshot, contentType: 'image/png' });
      }
      if (optimization === 'O0') {
        await page.getByRole('button', { name: /^SSA\s/ }).click();
        await expect(page.locator('.react-flow__node-ssa').first()).toBeVisible({ timeout: 30_000 });
      }

      const evidence = {
        mode: collectOnly ? 'collect-only diagnostic (threshold not asserted)' : 'strict',
        strictBudgetMs,
        case: sample.name,
        optimization,
        repeat,
        viewport,
        rendered,
        clickToPaintMs: paint.clickToPaintMs,
        paint,
        transport: { post: targetTrace.post, postResponse: targetTrace.postResponse, completedGet: terminal },
      };
      await testInfo.attach('actual-latency.json', { body: JSON.stringify(evidence, null, 2), contentType: 'application/json' });
      console.log(JSON.stringify(evidence));
      assertBudget(paint.clickToPaintMs);
    });
  }
}
