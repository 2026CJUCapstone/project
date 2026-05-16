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
  test("loads the app from /webcompiler and shows the default example", async ({ page }) => {
    await page.goto("/webcompiler/");

    await expect(page.getByText("B++ Online Compiler")).toBeVisible();
    await expect(page.getByTestId("compile-run-button")).toBeVisible();
    await expect(page.getByTestId("output-console")).not.toContainText("> _");
    await expect(page.locator(".view-lines").first()).toContainText("var spf: [101]i64;");
    await expect(page.locator(".view-lines").first()).toContainText("// spf[i] = i의 가장 작은 소인수");
  });

  test("runs B++ code through the browser at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/");
    await page.evaluate((code) => {
      window.localStorage.setItem("b-compiler-editor-code", code);
    }, validBppProgram);
    await page.reload();
    await expect(page.locator(".view-lines").first()).toContainText('emitln("Hello from Playwright");');

    await page.getByTestId("compile-run-button").click();

    const outputConsole = page.getByTestId("output-console");
    await expect(outputConsole).toContainText("BPP 컴파일 및 실행을 시작합니다.", { timeout: 30000 });
    await expect(outputConsole).toContainText("Hello from Playwright", { timeout: 30000 });
    await expect(outputConsole).toContainText("프로그램이 종료되었습니다. (exit code 0)", { timeout: 30000 });
  });

  test("loads the leaderboard route at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/leaderboard");

    await expect(page.getByRole("heading", { name: "리더보드" })).toBeVisible();
    await expect(page.getByText("전체 랭킹")).toBeVisible();
    await expect(page.getByText("순위", { exact: true })).toBeVisible();
    await expect(page.getByText("사용자", { exact: true })).toBeVisible();
    await expect(page.locator("div.text-right").filter({ hasText: /^점수$/ })).toBeVisible();
  });

  test("accepts terminal input and renders terminal output at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/");
    await page.evaluate((code) => {
      window.localStorage.setItem("b-compiler-editor-code", code);
    }, interactivePythonProgram);
    await page.reload();
    await expect(page.locator(".view-lines").first()).toContainText("line = input()");

    await page.getByRole("combobox", { name: "실행 언어 선택" }).selectOption("python");

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
