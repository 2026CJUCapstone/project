import { expect, test, type Page } from '@playwright/test';

const code = 'import emitln from std.io;\n// 한글 😀\nfunc main() -> u64 {\n    emitln("안녕 😀");\n    return 0;\n}\n';
const range = (text: string) => {
  const start = code.indexOf(text), end = start + text.length;
  const position = (offset: number) => {
    const lines = code.slice(0, offset).split('\n');
    return { line: lines.length, column: Buffer.byteLength(lines[lines.length - 1]) + 1 };
  };
  const first = position(start), last = position(end);
  return { file: 'main.bpp', startLine: first.line, startColumn: first.column,
    endLine: last.line, endColumn: last.column, startOffset: Buffer.byteLength(code.slice(0, start)), endOffset: Buffer.byteLength(code.slice(0, end)) };
};
const callRange = range('emitln("안녕 😀");');
const returnRange = range('return 0;');
const source = {
  file: 'main.bpp',
  startLine: 1,
  startColumn: 1,
  endLine: 7,
  endColumn: 1,
  startOffset: 0,
  endOffset: Buffer.byteLength(code),
};

const compileResult = {
  success: true,
  execution_time: 8,
  errors: [],
  warnings: [],
  metadata: { optimization_level: 0, source_range_semantics: { columnEncoding: 'byte', offsetEncoding: 'byte', endColumn: 'exclusive' } },
  ast: {
    nodes: [
      { id: 'program', type: 'Program', label: 'Program', children: ['main'], sourceRanges: [source] },
      { id: 'main', type: 'FunctionDecl', label: 'main', children: ['call', 'return'], sourceRanges: [source] },
      { id: 'call', type: 'CallExpr', label: 'emitln', children: [], sourceRanges: [callRange] },
      { id: 'return', type: 'ReturnStmt', label: 'return 0', children: [], sourceRanges: [returnRange] },
    ],
    edges: [
      { from: 'program', to: 'main', label: 'body' },
      { from: 'main', to: 'call', label: 'statement' },
      { from: 'main', to: 'return', label: 'statement' },
    ],
  },
  ssa: {
    blocks: [
      { id: 'entry', label: 'main · entry', functionId: 'main', isEntry: true, instructions: ['call @emitln', 'ret 0'], instructionIds: ['i1', 'i2'], instructionSourceRanges: [[callRange], [returnRange]], sourceRanges: [source], predecessors: [], successors: [] },
    ],
    edges: [],
  },
  ir: { instructions: [{ id: 'ir-1', opcode: 'call', operands: ['@emitln'], sourceRanges: [callRange], metadata: { ssaInstructionId: 'i1' } }, { id: 'ir-2', opcode: 'ret', operands: ['0'], sourceRanges: [returnRange] }] },
  asm: { lines: [{ address: '0', instruction: 'call', operands: ['emitln'], sourceRanges: [callRange] }, { address: '1', instruction: 'ret', operands: [], sourceRanges: [returnRange] }] },
};

const expectInspectorBelowCanvas = async (page: Page) => {
  const graph = page.locator('.graph-interactive').filter({ has: page.locator('aside[aria-label="선택한 노드 상세"]') }).first();
  const canvas = graph.locator('[data-testid="graph-canvas"]');
  const inspector = graph.locator('aside[aria-label="선택한 노드 상세"]');
  await expect(graph).toBeVisible();
  await expect(canvas).toBeVisible();
  await expect(inspector).toBeVisible();
  const canvasBox = await canvas.boundingBox();
  const inspectorBox = await inspector.boundingBox();
  const graphBox = await graph.boundingBox();
  expect(canvasBox).not.toBeNull();
  expect(inspectorBox).not.toBeNull();
  expect(graphBox).not.toBeNull();
  expect(inspectorBox!.y).toBeGreaterThanOrEqual(canvasBox!.y + canvasBox!.height - 1);
  expect(inspectorBox!.x).toBeGreaterThanOrEqual(graphBox!.x - 1);
  expect(inspectorBox!.x + inspectorBox!.width).toBeLessThanOrEqual(graphBox!.x + graphBox!.width + 1);
  expect(inspectorBox!.y + inspectorBox!.height).toBeLessThanOrEqual(graphBox!.y + graphBox!.height + 1);
};

const expectStageNavigationFits = async (page: Page) => {
  const workspace = page.locator('[data-graph-workspace]').first();
  const stageTabs = workspace.locator('.graph-stage-tabs');
  await expect(stageTabs).toBeVisible();
  await expect.poll(() => stageTabs.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  const workspaceBox = await workspace.boundingBox();
  const stageTabsBox = await stageTabs.boundingBox();
  expect(workspaceBox).not.toBeNull();
  expect(stageTabsBox).not.toBeNull();
  expect(stageTabsBox!.x).toBeGreaterThanOrEqual(workspaceBox!.x - 1);
  expect(stageTabsBox!.x + stageTabsBox!.width).toBeLessThanOrEqual(workspaceBox!.x + workspaceBox!.width + 1);
};

test('compiler graph supports drag, search, focus, collapse, layout and source navigation', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));

  await page.route('**/api/v1/executions', async (route) => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ id: 'graph-e2e', status: 'queued', receivedAt: 'now', requestId: 'graph-e2e-request' }),
    });
  });
  await page.route('**/api/v1/executions/graph-e2e', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ id: 'graph-e2e', status: 'completed', receivedAt: 'now', result: { ok: true, value: compileResult } }),
    });
  });

  await page.goto('/ide');
  await expect(page.getByTitle('기본 코드 불러오기')).toBeEnabled();
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true });
  await editor.focus();
  await editor.press('Control+a');
  await page.keyboard.insertText(code);
  await expect(page.locator('.monaco-editor .view-lines')).toContainText('안녕');
  await page.getByRole('button', { name: '컴파일 (Ctrl+Shift+B)' }).click();
  const astNodes = page.locator('.react-flow__node-ast');
  await expect(astNodes).toHaveCount(4);
  await expect(page.getByPlaceholder('AST 노드 검색')).toBeVisible();

  // Real Monaco selection, after a multibyte comment and before an emoji.
  await editor.focus();
  await editor.press('Control+Home');
  await editor.press('ArrowDown');
  await editor.press('ArrowDown');
  await editor.press('ArrowDown');
  await editor.press('Home');
  await editor.press('Shift+End');
  await expect(page.locator('[data-id="call"] [data-source-highlight="true"]')).toHaveCount(1);
  await expect(page.locator('[data-id="return"] [data-source-highlight="true"]')).toHaveCount(0);
  await editor.press('Shift+ArrowDown');
  await expect(page.locator('[data-id="return"] [data-source-highlight="true"]')).toHaveCount(1);

  const callLine = await page.locator('.view-line').filter({ hasText: 'emitln("안녕' }).locator(':scope > span').boundingBox();
  const returnLine = await page.locator('.view-line').filter({ hasText: 'return 0;' }).locator(':scope > span').boundingBox();
  expect(callLine).not.toBeNull();
  expect(returnLine).not.toBeNull();
  await page.mouse.move(callLine!.x + 1, callLine!.y + callLine!.height / 2);
  await page.mouse.down();
  await page.mouse.move(returnLine!.x + returnLine!.width, returnLine!.y + returnLine!.height / 2, { steps: 12 });
  await page.mouse.up();
  await expect(page.locator('[data-id="call"] [data-source-highlight="true"]')).toHaveCount(1);
  await expect(page.locator('[data-id="return"] [data-source-highlight="true"]')).toHaveCount(1);

  const mainNode = astNodes.filter({ hasText: 'FunctionDecl' });
  const beforeDrag = await mainNode.getAttribute('style');
  const box = await mainNode.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width / 2 + 100, box!.y + box!.height / 2 + 45, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => mainNode.getAttribute('style')).not.toBe(beforeDrag);
  const draggedPosition = await mainNode.evaluate(element => (element as HTMLElement).style.transform);
  await editor.focus();
  await editor.press('Control+Home');
  await editor.press('Shift+End');
  await expect.poll(() => mainNode.evaluate(element => (element as HTMLElement).style.transform)).toBe(draggedPosition);

  const search = page.getByPlaceholder('AST 노드 검색');
  await search.fill('CallExpr');
  await search.press('Enter');
  await expect(page.getByText('CallExpr', { exact: true }).last()).toBeVisible();
  await expectInspectorBelowCanvas(page);
  await page.getByTitle('라이트 테마로 전환').click();
  await expect(page.getByTitle('다크 테마로 전환')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('compiler-graph-ast-interactions-light.png'), fullPage: true });
  await page.getByTitle('다크 테마로 전환').click();
  await expect(page.getByRole('button', { name: '소스로 이동' })).toBeEnabled();
  await page.getByRole('button', { name: '관계 집중' }).click();
  await expect(page.getByRole('button', { name: '관계 집중 해제' })).toBeVisible();
  await page.getByRole('button', { name: '관계 집중 해제' }).click();

  await search.fill('Program');
  await search.press('Enter');
  await page.getByRole('button', { name: '하위 접기' }).click();
  await expect(astNodes).toHaveCount(1);
  await page.getByRole('button', { name: '하위 펼치기' }).click();
  await expect(astNodes).toHaveCount(4);

  await page.getByTitle('좌우 레이아웃으로 전환').click();
  await expect(page.getByTitle('상하 레이아웃으로 전환')).toBeVisible();
  await page.getByTitle('자동 배치로 초기화').click();
  await page.getByTitle('상세 닫기').click();
  await page.getByTitle('미니맵 보기').click();
  await expect(page.locator('.react-flow__minimap')).toBeVisible();
  await page.getByTitle('미니맵 숨기기').click();
  await page.screenshot({ path: testInfo.outputPath('compiler-graph-ast-interactions.png'), fullPage: true });

  await page.getByRole('button', { name: /^IR\s/ }).click();
  const mappedIrLine = page.getByRole('button', { name: /call.*@emitln/ });
  await expect(mappedIrLine).toHaveAttribute('title', '이 명령을 만든 소스 코드로 이동');
  await mappedIrLine.click();
  await expect(page.locator('.monaco-editor .selected-text').first()).toBeVisible();

  await page.getByRole('button', { name: /^SSA\s/ }).click();
  await expect(page.locator('.react-flow__node-ssa')).toHaveCount(1);
  await expect(page.getByPlaceholder('SSA 노드 검색')).toBeVisible();
  await page.getByRole('button', { name: '단계 연결', exact: true }).click();
  await expect(page.getByRole('region', { name: '단계별 변환 연결' })).toContainText('같은 소스 범위');
  await page.getByRole('button', { name: '제어 흐름', exact: true }).click();
  await page.getByLabel('탐색 시작 블록').selectOption('entry');
  await expect(page.getByRole('region', { name: '제어 흐름 탐색' })).toContainText('경로 끝');
  await page.getByRole('button', { name: '최적화 비교', exact: true }).click();
  await page.getByRole('button', { name: '최적화 전후 비교하기' }).click();
  await expect(page.getByRole('region', { name: '최적화 전후 비교' })).toContainText('출력 변화 없음');

  await editor.focus();
  await editor.press('Control+End');
  await page.keyboard.insertText('// changed');
  await expect(page.getByText('코드가 변경되어 이전 결과와의 위치 연결을 멈췄습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: '최적화 전후 비교하기' })).toBeDisabled();
  await page.getByRole('button', { name: /^IR\s/ }).click();
  await expect(page.getByRole('button', { name: /call.*@emitln/ })).toBeDisabled();

  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 844 });
    if (width < 768) await page.getByRole('tab', { name: '그래프', exact: true }).click();
    await page.getByRole('button', { name: '제어 흐름', exact: true }).click();
    await expect(page.getByLabel('탐색 시작 블록')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (width < 768) await expectStageNavigationFits(page);
    await page.screenshot({ path: testInfo.outputPath(`compiler-graph-${width}.png`), fullPage: true });
    await page.getByRole('button', { name: '제어 흐름', exact: true }).click();
  }
  await page.getByRole('tab', { name: '코드', exact: true }).click();
  await editor.focus();
  await editor.press('Control+a');
  await page.keyboard.insertText(code);
  await page.getByRole('tab', { name: '그래프', exact: true }).click();
  await page.getByPlaceholder('SSA 노드 검색').fill('entry');
  await page.getByPlaceholder('SSA 노드 검색').press('Enter');
  await expect(page.getByRole('tab', { name: '그래프', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('button', { name: '소스로 이동', exact: true }).click();
  await expect(page.getByRole('tab', { name: '코드', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.monaco-editor .selected-text').first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('compiler-graph-interactions.png'), fullPage: true });
  expect(pageErrors).toEqual([]);
});

test('six exploration features stay linked and usable at desktop, tablet and mobile sizes', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const enriched = structuredClone(compileResult) as any;
  enriched.ast.nodes[2].sourceRanges = [{ ...callRange, astNodeId: 'call' }];
  enriched.ast.nodes[3].sourceRanges = [{ ...returnRange, astNodeId: 'return' }];
  enriched.ssa.blocks = [
    { id: 'entry', functionId: 'main', label: 'main · entry', isEntry: true, instructions: ['r1 = call @emitln'], instructionDetails: [{ id: 'i1', opcode: 'call', definitions: ['r1'], uses: [], complete: true }], instructionSourceRanges: [[callRange]], sourceRanges: [callRange], successors: ['exit'] },
    { id: 'exit', functionId: 'main', label: 'main · exit', instructions: ['ret r1'], instructionDetails: [{ id: 'i2', opcode: 'ret', definitions: [], uses: ['r1'], complete: true }], instructionSourceRanges: [[returnRange]], sourceRanges: [returnRange], predecessors: ['entry'] },
  ];
  enriched.ssa.edges = [{ from: 'entry', to: 'exit' }];
  enriched.ssa.optimizationSummaries = [{ functionId: 'main', functionName: 'main', level: 1, scope: 'function', evidence: 'compiler-counters-v1', counters: { constantOperands: 2, unreachableBlocks: 1 } }];
  await page.route('**/api/v1/executions', route => route.fulfill({ status: 202, json: { id: 'six-features', status: 'queued', receivedAt: 'now', requestId: 'six-features' } }));
  await page.route('**/api/v1/executions/six-features', route => route.fulfill({ json: { id: 'six-features', status: 'completed', result: { ok: true, value: enriched } } }));
  await page.goto('/ide');
  const editor = page.getByRole('textbox', { name: 'Editor content', exact: true });
  await editor.focus(); await editor.press('Control+a'); await page.keyboard.insertText(code);
  await page.getByRole('button', { name: '컴파일 (Ctrl+Shift+B)' }).click();
  await expect(page.locator('.react-flow__node-ast')).toHaveCount(4);
  await editor.focus(); await editor.press('Control+Home');
  for (let i = 0; i < 3; i++) await editor.press('ArrowDown');
  await editor.press('Home'); await editor.press('Shift+End');
  await page.getByRole('button', { name: '선택 영역만 보기' }).click();
  await expect(page.locator('.react-flow__node-ast')).toHaveCount(1);
  await expect(page.locator('[data-id="call"]')).toBeVisible();
  await page.getByRole('button', { name: '주변 연결 펼치기' }).click();
  await expect(page.locator('.react-flow__node-ast')).toHaveCount(2);
  await page.getByRole('button', { name: '선택 집중 해제' }).click();
  await expect(page.locator('.react-flow__node-ast')).toHaveCount(4);

  await page.getByTitle('탐색 크게 보기').click();
  await page.getByLabel('단계 나란히 보기').selectOption('AST-SSA');
  await expect(page.getByRole('region', { name: 'AST 비교 패널' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'SSA 비교 패널' })).toBeVisible();
  await expect(page.locator('[data-id="call"] [data-source-highlight="true"]')).toBeVisible();
  await expect(page.locator('[data-id="entry"] [data-source-highlight="true"]')).toBeVisible();
  const left = await page.getByRole('region', { name: 'AST 비교 패널' }).boundingBox();
  const right = await page.getByRole('region', { name: 'SSA 비교 패널' }).boundingBox();
  expect(right!.x).toBeGreaterThan(left!.x + left!.width - 2);
  await page.getByPlaceholder('AST 노드 검색').fill('CallExpr');
  await page.getByPlaceholder('AST 노드 검색').press('Enter');
  await expectInspectorBelowCanvas(page);
  await expect(page.locator('[data-mapping-quality="expression"]')).toBeVisible();
  await page.getByTitle('r1 정의·사용 추적').first().click();
  await expect(page.getByRole('region', { name: '변수 흐름 추적' })).toContainText('정의 1곳 / 사용 1곳');
  await expect(page.locator('.react-flow__edge').filter({ hasText: 'r1' })).toHaveCount(1);
  await expect(page.locator('[data-value-highlight="true"]')).toHaveCount(2);
  await page.screenshot({ path: testInfo.outputPath('six-features-side-by-side.png'), fullPage: true });
  await page.getByLabel('단계 나란히 보기').selectOption('IR-ASM');
  await page.getByRole('region', { name: 'IR 비교 패널' }).getByRole('button', { name: /call.*@emitln/ }).click();
  await expect(page.getByRole('region', { name: 'ASM 비교 패널' }).getByRole('button', { name: /call.*emitln/ })).toHaveClass(/bg-amber-50/);
  await page.getByRole('button', { name: '최적화 비교', exact: true }).click();
  await page.getByRole('button', { name: '최적화 전후 비교하기' }).click();
  await expect(page.getByRole('region', { name: '최적화 전후 비교' })).toContainText('상수로 확정된 피연산자 대체');
  for (const width of [1024, 390]) {
    await page.setViewportSize({ width, height: 844 });
    if (width < 768) await page.getByRole('tab', { name: '그래프', exact: true }).click();
    await page.getByLabel('단계 나란히 보기').selectOption('AST-SSA');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (width < 768) await expectStageNavigationFits(page);
    await expect(page.getByRole('region', { name: 'SSA 비교 패널' })).toBeAttached();
    const secondPanel = await page.getByRole('region', { name: 'SSA 비교 패널' }).boundingBox();
    const footer = await page.getByTestId('compiler-stage-footer').boundingBox();
    expect(footer!.y).toBeGreaterThanOrEqual(secondPanel!.y + secondPanel!.height - 2);
    await page.screenshot({ path: testInfo.outputPath(`six-features-${width}.png`), fullPage: true });
  }
  await page.getByLabel('단계 나란히 보기').selectOption('none');
  await page.getByRole('button', { name: /B\+\+ 예제 따라하기/ }).click();
  const tutorial = page.getByRole('region', { name: 'B++ 예제 따라하기' });
  page.once('dialog', dialog => dialog.dismiss());
  await tutorial.getByRole('button', { name: '예제 불러오기' }).click();
  await expect(tutorial.getByRole('button', { name: '다음 단계' })).toBeDisabled();
  page.once('dialog', dialog => dialog.accept());
  await tutorial.getByRole('button', { name: '예제 불러오기' }).click();
  await expect(tutorial.getByRole('button', { name: '다음 단계' })).toBeEnabled();
  await tutorial.getByRole('button', { name: '다음 단계' }).click();
  await expect(tutorial.getByRole('button', { name: '예제 컴파일' })).toBeEnabled();
  expect(errors).toEqual([]);
});
