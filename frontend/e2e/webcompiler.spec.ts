import { expect, test } from "@playwright/test";

const validBppProgram = `import emitln from std.io;

func main() -> u64 {
    emitln("Hello from Playwright");
    return 0;
}
`;

const interactiveBppProgram = `import std.io;

func main() -> u64 {
    var line: number = input();
    print("program says: ");
    println(line);
    return 0;
}
`;

const interactivePythonProgram = `line = input()
print(f"program says: {line}")
`;

test.describe("webcompiler browser e2e", () => {
  test("introduces the platform from /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/");

    await expect(page.getByText("B++ Online Compiler")).toBeVisible();
    await expect(page.getByRole("heading", { name: /브라우저에서 코드를 실행하고/ })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("B++의 컴파일 과정을 살펴보세요.");
    await expect(page.getByRole("button", { name: "코드 실행하기", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "B++는 어떤 언어인가요?" })).toContainText("직접 작성한 코드가 어떻게 분석되고 실행 파일로 바뀌는지 단계별로 살펴볼 수 있습니다.");
    await expect(page.getByText("B++ 코드의 AST와 SSA는 그래프로, IR과 어셈블리 코드는 텍스트로 확인할 수 있습니다.")).toBeVisible();
    await expect(page.getByRole("button", { name: "커뮤니티 가기", exact: true })).toBeVisible();
    await expect(page.getByTestId("landing-page")).not.toContainText("READY TO BUILD?");
  });

  test("loads the IDE and shows the default example", async ({ page }) => {
    await page.goto("/webcompiler/ide");

    await expect(page.getByTestId("compile-run-button")).toBeVisible();
    await expect(page.getByTestId("output-console")).not.toContainText("> _");
    await expect(page.locator(".view-lines").first()).toContainText("var spf: [101]i64;");
    await expect(page.locator(".view-lines").first()).toContainText("// spf[i] = i의 가장 작은 소인수");
  });

  test("runs B++ code through the browser at /webcompiler", async ({ page }) => {
    // This is a real public compiler lifecycle, not a mocked UI transition.
    // Keep a finite end-to-end budget while retaining the queue, stdout, and
    // terminal-exit assertions below.
    test.setTimeout(60_000);
    await page.goto("/webcompiler/ide");
    await page.evaluate((code) => {
      window.localStorage.setItem("b-compiler-editor-code", code);
    }, validBppProgram);
    await page.reload();
    await expect(page.locator(".view-lines").first()).toContainText('emitln("Hello from Playwright");');

    await page.getByTestId("compile-run-button").click();

    const outputConsole = page.getByTestId("output-console");
    await expect(outputConsole).toContainText("> 실행 대기열에 등록되었습니다.", { timeout: 30000 });
    await expect(outputConsole).toContainText("Hello from Playwright", { timeout: 30000 });
    await expect(outputConsole).toContainText("프로그램이 종료되었습니다. (exit code 0)", { timeout: 30000 });
  });

  test("loads the leaderboard route at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/leaderboard");

    await expect(page.getByRole("heading", { name: "리더보드" })).toBeVisible();
    await expect(page.getByText("전체 랭킹")).toBeVisible();
    await expect(page.getByText("순위", { exact: true })).toBeVisible();
    await expect(page.getByText("사용자", { exact: true })).toBeVisible();
    await expect(page.getByText("레이팅", { exact: true })).toBeVisible();
    await expect(page.getByText("XP", { exact: true })).toBeVisible();
  });

  test("accepts terminal input and renders terminal output at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/ide");
    await expect(page.locator(".view-lines").first()).toBeVisible();
    // Target the visible native select directly.  `getByText("Python")` can
    // resolve the hidden option node and cannot drive a real public browser.
    const languageSelect = page.locator('select[title="실행 언어 선택"]');
    await expect(languageSelect).toBeVisible();
    await languageSelect.selectOption("python");
    await page.locator(".view-lines").first().click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.insertText(interactivePythonProgram);
    await expect(page.locator(".view-lines").first()).toContainText("line = input()");

    await page.getByTestId("terminal-tab").click();

    const terminalInput = page.getByTestId("terminal-input");
    const terminalOutput = page.getByTestId("terminal-output");

    await expect(terminalInput).toBeDisabled();
    await expect(terminalOutput).toContainText("상단 실행 버튼을 누르면");

    await page.getByTestId("compile-run-button").click();
    await expect(terminalInput).toBeEnabled({ timeout: 30000 });
    await terminalInput.fill("42");
    await terminalInput.press("Enter");

    await expect(terminalOutput.locator('[data-terminal-line-type="input"]').filter({ hasText: "stdin> 42" }).first()).toBeVisible({ timeout: 30000 });
    await expect(terminalOutput.locator('[data-terminal-line-type="output"]').filter({ hasText: "program says:" }).first()).toBeVisible({ timeout: 30000 });
    await expect(terminalOutput.locator('[data-terminal-line-type="output"]').filter({ hasText: "42" }).first()).toBeVisible({ timeout: 30000 });
    await expect(terminalOutput).toContainText("exit code 0", { timeout: 30000 });

    await page.getByTestId("output-tab").click();
    await expect(page.getByTestId("output-console")).not.toContainText("stdin> 42");
  });
});
