import { expect, test } from "@playwright/test";

const validBppProgram = `import emitln from std.io;

func main() -> u64 {
    emitln("Hello from Playwright");
    return 0;
}
`;

const interactiveBppProgram = `import std.io;

func main() -> u64 {
    var line: u64 = input();
    emit("program says: ");
    emitln(line);
    return 0;
}
`;

test.describe("webcompiler browser e2e", () => {
  test("loads the app from /webcompiler and shows the default example", async ({ page }) => {
    await page.goto("/webcompiler/");

    await expect(page.getByText("B++ Online Compiler")).toBeVisible();
    await expect(page.getByTestId("compile-run-button")).toBeVisible();
    await expect(page.getByTestId("output-console")).not.toContainText("> _");
    await expect(page.locator(".view-lines").first()).toContainText('println("Hello from B++!!");');
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
    await expect(outputConsole).toContainText("실행 완료", { timeout: 30000 });
    await expect(outputConsole).toContainText("Hello from Playwright", { timeout: 30000 });
  });

  test("loads the leaderboard route at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/leaderboard");

    await expect(page.getByRole("heading", { name: "리더보드" })).toBeVisible();
    await expect(page.getByText("전체 랭킹")).toBeVisible();
    await expect(page.getByText("순위", { exact: true })).toBeVisible();
    await expect(page.getByText("사용자", { exact: true })).toBeVisible();
    await expect(page.getByText("점수", { exact: true })).toBeVisible();
  });

  test("accepts terminal input and renders terminal output at /webcompiler", async ({ page }) => {
    await page.goto("/webcompiler/");
    await page.evaluate((code) => {
      window.localStorage.setItem("b-compiler-editor-code", code);
    }, interactiveBppProgram);
    await page.reload();
    await expect(page.locator(".view-lines").first()).toContainText("input();");

    await page.getByTestId("terminal-tab").click();

    const terminalInput = page.getByTestId("terminal-input");
    const terminalOutput = page.getByTestId("terminal-output");

    await expect(terminalInput).toBeDisabled();
    await expect(terminalOutput).toContainText("연결 버튼을 눌렀을 때만");

    await page.getByTestId("terminal-connect-button").click();
    await expect(terminalInput).toBeEnabled({ timeout: 30000 });
    await terminalInput.fill("terminal-stdin-ok");
    await terminalInput.press("Enter");

    await expect(terminalOutput).toContainText("stdin> terminal-stdin-ok", { timeout: 30000 });
    await expect(terminalOutput).toContainText("program says: terminal-stdin-ok", { timeout: 30000 });
    await expect(terminalOutput).toContainText("exit code 0", { timeout: 30000 });

    await page.getByTestId("output-tab").click();
    await expect(page.getByTestId("output-console")).not.toContainText("terminal-stdin-ok");
  });
});
