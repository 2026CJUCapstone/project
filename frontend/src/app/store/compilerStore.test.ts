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

  it("sends a snapshotted token only in the terminal start frame and never reconnects after loss", async () => {
    class FakeWebSocket {
      static CLOSED = 3;
      static instances: FakeWebSocket[] = [];
      readyState = 1;
      sent: string[] = [];
      onopen: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: ((event: { code: number }) => void) | null = null;
      constructor(public url: string) { FakeWebSocket.instances.push(this); }
      send(value: string) { this.sent.push(value); }
      close() { this.readyState = FakeWebSocket.CLOSED; }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.mocked(compileCode).mockResolvedValue({ success: true, executionTime: 1 });
    vi.mocked(checkHealth).mockResolvedValue({ status: "ok" });
    localStorage.setItem("authToken", "private-jwt");
    useCompilerStore.getState().setCode("print(1)");

    const starting = useCompilerStore.getState().compileAndStartTerminal();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    expect(socket.url).not.toContain("private-jwt");
    expect(new URL(socket.url).search).toBe("");
    localStorage.setItem("authToken", "changed-after-connect");
    socket.onopen?.();
    await starting;

    expect(JSON.parse(socket.sent[0])).toMatchObject({ type: "start", code: "print(1)", token: "private-jwt" });
    socket.onclose?.({ code: 1006 });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(FakeWebSocket.instances).toHaveLength(1);
    const lostLines = useCompilerStore.getState().terminalLines;
    expect(lostLines[lostLines.length - 1]?.text).toContain("자동으로 재개되지 않으며");
    expect(useCompilerStore.getState().isRunning).toBe(false);
    vi.unstubAllGlobals();
  });

  it("does not include an absent token and labels a normal terminal close", async () => {
    class FakeWebSocket {
      static CLOSED = 3;
      static instances: FakeWebSocket[] = [];
      readyState = 1;
      sent: string[] = [];
      onopen: (() => void) | null = null;
      onclose: ((event: { code: number }) => void) | null = null;
      constructor(public url: string) { FakeWebSocket.instances.push(this); }
      send(value: string) { this.sent.push(value); }
      close() { this.readyState = FakeWebSocket.CLOSED; }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.mocked(compileCode).mockResolvedValue({ success: true, executionTime: 1 });
    vi.mocked(checkHealth).mockResolvedValue({ status: "ok" });
    useCompilerStore.getState().setCode("print(2)");

    const starting = useCompilerStore.getState().compileAndStartTerminal();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    socket.onopen?.();
    await starting;
    expect(JSON.parse(socket.sent[0])).not.toHaveProperty("token");
    socket.onclose?.({ code: 1000 });
    const closedLines = useCompilerStore.getState().terminalLines;
    expect(closedLines[closedLines.length - 1]?.text).toBe("터미널 실행이 정상 종료되었습니다.");
    vi.unstubAllGlobals();
  });

  it("ignores a delayed close from the replaced socket while the new terminal stays active", async () => {
    class FakeWebSocket {
      static CLOSED = 3;
      static instances: FakeWebSocket[] = [];
      readyState = 1;
      sent: string[] = [];
      onopen: (() => void) | null = null;
      onclose: ((event: { code: number }) => void) | null = null;
      constructor(public url: string) { FakeWebSocket.instances.push(this); }
      send(value: string) { this.sent.push(value); }
      close() { this.readyState = FakeWebSocket.CLOSED; }
    }
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.mocked(compileCode).mockResolvedValue({ success: true, executionTime: 1 });
    vi.mocked(checkHealth).mockResolvedValue({ status: "ok" });
    useCompilerStore.getState().setCode("print(3)");

    const firstStart = useCompilerStore.getState().compileAndStartTerminal();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const oldSocket = FakeWebSocket.instances[0];
    oldSocket.onopen?.();
    await firstStart;
    useCompilerStore.getState().cancelRun();

    const secondStart = useCompilerStore.getState().compileAndStartTerminal();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    const newSocket = FakeWebSocket.instances[1];
    newSocket.onopen?.();
    await secondStart;
    const currentLines = useCompilerStore.getState().terminalLines;

    oldSocket.onclose?.({ code: 1006 });
    expect(useCompilerStore.getState().isRunning).toBe(true);
    expect(useCompilerStore.getState().terminalStatus).toBe("connected");
    expect(useCompilerStore.getState().terminalLines).toEqual(currentLines);
    expect(FakeWebSocket.instances).toHaveLength(2);

    newSocket.onclose?.({ code: 1000 });
    vi.unstubAllGlobals();
  });
});
