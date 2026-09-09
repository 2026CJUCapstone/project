import { beforeEach, describe, expect, it, vi } from "vitest";
import { useCompilerStore } from "./compilerStore";
import { checkHealth, compileCode, executeCode } from "../services/compilerApi";

vi.mock("../services/compilerApi", () => ({
  checkHealth: vi.fn(),
  compileCode: vi.fn(),
  executeCode: vi.fn(),
}));

const initialState = useCompilerStore.getState();

describe("compilerStore", () => {
  beforeEach(() => {
    useCompilerStore.setState(initialState, true);
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("warns instead of compiling when code is empty", async () => {
    await useCompilerStore.getState().compile();

    const state = useCompilerStore.getState();
    expect(compileCode).not.toHaveBeenCalled();
    expect(state.output.some((line) => line.text.includes("컴파일할 코드가 없습니다"))).toBe(true);
  });

  it("runs code after a successful compile", async () => {
    vi.mocked(compileCode).mockResolvedValue({
      success: true,
      executionTime: 12,
      errors: [],
      warnings: [],
      metadata: { nodeCount: 2, optimizationLevel: 0 },
    });
    vi.mocked(checkHealth).mockResolvedValue({ status: "ok", version: "1.0.0" });
    vi.mocked(executeCode).mockResolvedValue({
      success: true,
      stdout: "42\n",
      stderr: "",
      exitCode: 0,
      executionTime: 35,
    });

    useCompilerStore.getState().setCode('import emitln from std.io;\nfunc main() -> u64 { emitln("42"); return 0; }\n');

    await useCompilerStore.getState().compileAndRun();

    const state = useCompilerStore.getState();
    expect(compileCode).toHaveBeenCalledTimes(1);
    expect(checkHealth).toHaveBeenCalledTimes(1);
    expect(executeCode).toHaveBeenCalledTimes(1);
    expect(state.lastCompile?.success).toBe(true);
    expect(state.lastExecution?.stdout).toBe("42\n");
    expect(state.output.some((line) => line.text.includes("컴파일 성공"))).toBe(true);
    expect(state.output.some((line) => line.text.includes("실행 완료"))).toBe(true);
    expect(state.output.some((line) => line.text.includes("42"))).toBe(true);
  });

  it("marks backend offline when health check fails", async () => {
    vi.mocked(checkHealth).mockRejectedValue(new Error("백엔드 연결 실패"));

    useCompilerStore.getState().setCode('print("x")');

    await useCompilerStore.getState().runCode();

    const state = useCompilerStore.getState();
    expect(executeCode).not.toHaveBeenCalled();
    expect(state.backendStatus).toBe("offline");
    expect(state.lastError).toContain("백엔드 연결 실패");
  });

  it("stores main and problem code in separate slots", () => {
    const store = useCompilerStore.getState();

    store.saveCode("main code", "main");
    store.saveCode("problem one", "problem:p-1");
    store.saveCode("problem two", "problem:p-2");

    expect(store.loadCode("main")).toBe("main code");
    expect(store.loadCode("problem:p-1")).toBe("problem one");
    expect(store.loadCode("problem:p-2")).toBe("problem two");
    expect(store.loadCodeSavedAt("main")).toEqual(expect.any(Number));
  });

  it("replaces code on an explicit language selection and clears stale compile state", () => {
    useCompilerStore.setState({ code: 'old code', lastCompile: { success: true, executionTime: 1 }, lastCompiledCode: 'old code' });
    useCompilerStore.getState().selectLanguage('python');
    const selected = useCompilerStore.getState();
    expect(selected.language).toBe('python');
    expect(selected.code).toContain('print(');
    expect(selected.lastCompile).toBeNull();
    expect(selected.lastCompiledCode).toBeNull();

    selected.setCode('custom Python code');
    selected.selectLanguage('python');
    expect(useCompilerStore.getState().code).toBe('custom Python code');
    selected.setLanguage('java');
    expect(useCompilerStore.getState().code).toBe('custom Python code');
  });

  it("persists the language with the code while supporting older saved code", () => {
    const store = useCompilerStore.getState();
    expect(store.loadCodeLanguage('main')).toBeNull();
    store.selectLanguage('java');
    store.saveCode(useCompilerStore.getState().code, 'main');
    store.selectLanguage('cpp');
    store.saveCode(useCompilerStore.getState().code, 'problem:p-1');
    expect(store.loadCodeLanguage('main')).toBe('java');
    expect(store.loadCodeLanguage('problem:p-1')).toBe('cpp');
    expect(store.loadCode('main')).toContain('public class Main');
  });
});
