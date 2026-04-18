import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Maximize2, Network, Plug, RefreshCw, Terminal as TerminalIcon, XCircle } from "lucide-react";
import { useCompilerStore } from "../store/compilerStore";

type ConsoleTab = "output" | "terminal";
type TerminalStatus = "disconnected" | "connecting" | "connected";
type TerminalLine = {
  type: "system" | "output" | "error";
  text: string;
};

function getTerminalWebSocketUrl(): string {
  const configuredWsUrl = import.meta.env.VITE_WS_URL;
  const baseFromRoute = import.meta.env.BASE_URL === "/" ? "" : import.meta.env.BASE_URL.replace(/\/$/, "");
  const baseValue = configuredWsUrl || import.meta.env.VITE_API_URL || baseFromRoute || window.location.origin;
  const url = new URL(baseValue, window.location.origin);

  url.protocol = url.protocol === "https:" || url.protocol === "wss:" ? "wss:" : "ws:";

  if (!url.pathname.endsWith("/ws/terminal")) {
    const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");
    url.pathname = `${path}/ws/terminal`;
  }

  url.search = "";
  url.hash = "";
  return url.toString();
}

const terminalStatusLabel: Record<TerminalStatus, string> = {
  disconnected: "Disconnected",
  connecting: "Connecting",
  connected: "Connected",
};

export function OutputConsole() {
  const { code, language, isGraphViewerOpen, setGraphViewerOpen, output, clearOutput, restartConsole, backendStatus, isRunning } = useCompilerStore();
  const [activeTab, setActiveTab] = useState<ConsoleTab>("output");
  const [terminalStatus, setTerminalStatus] = useState<TerminalStatus>("disconnected");
  const [terminalLines, setTerminalLines] = useState<TerminalLine[]>([]);
  const [terminalInput, setTerminalInput] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const terminalScrollRef = useRef<HTMLDivElement | null>(null);

  const appendTerminalLine = useCallback((line: TerminalLine) => {
    setTerminalLines((lines) => [...lines, line]);
  }, []);

  const closeTerminalSocket = useCallback(() => {
    const current = wsRef.current;
    wsRef.current = null;
    if (current && current.readyState !== WebSocket.CLOSED) {
      current.close();
    }
  }, []);

  const connectTerminal = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) {
      return;
    }

    if (!code.trim()) {
      appendTerminalLine({ type: "error", text: "실행할 코드가 없습니다." });
      return;
    }

    setTerminalStatus("connecting");
    appendTerminalLine({ type: "system", text: "프로그램 터미널 준비 중..." });

    const ws = new WebSocket(getTerminalWebSocketUrl());
    wsRef.current = ws;

    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      ws.send(JSON.stringify({ type: "start", code, language, optimize: false }));
      setTerminalStatus("connected");
      appendTerminalLine({ type: "system", text: `${language.toUpperCase()} 프로그램 stdin 연결됨` });
    };

    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return;
      appendTerminalLine({ type: "output", text: String(event.data) });
    };

    ws.onerror = () => {
      if (wsRef.current !== ws) return;
      appendTerminalLine({ type: "error", text: "터미널 연결 오류" });
    };

    ws.onclose = () => {
      if (wsRef.current !== ws) return;
      wsRef.current = null;
      setTerminalStatus("disconnected");
      appendTerminalLine({ type: "system", text: "터미널 연결 종료" });
    };
  }, [appendTerminalLine, code, language]);

  const openTerminalTab = () => {
    setActiveTab("terminal");
    connectTerminal();
  };

  const restartTerminal = () => {
    closeTerminalSocket();
    setTerminalLines([]);
    setTerminalStatus("disconnected");
    connectTerminal();
  };

  const disconnectTerminal = () => {
    closeTerminalSocket();
    setTerminalStatus("disconnected");
    appendTerminalLine({ type: "system", text: "터미널 연결 종료" });
  };

  const clearTerminal = () => {
    setTerminalLines([]);
  };

  const submitTerminalInput = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      appendTerminalLine({ type: "error", text: "터미널이 연결되어 있지 않습니다." });
      return;
    }

    ws.send(`${terminalInput}\n`);
    setTerminalInput("");
  };

  useEffect(() => {
    if (activeTab === "terminal") {
      terminalScrollRef.current?.scrollTo({
        top: terminalScrollRef.current.scrollHeight,
        behavior: "smooth",
      });
    }
  }, [activeTab, terminalLines]);

  useEffect(() => {
    return () => closeTerminalSocket();
  }, [closeTerminalSocket]);

  return (
    <div
      data-testid="output-console"
      className="flex flex-col h-full bg-gray-50 dark:bg-[#0d0d0d] font-mono text-sm shadow-[inset_0_2px_10px_rgba(0,0,0,0.05)] dark:shadow-[inset_0_2px_10px_rgba(0,0,0,0.5)] transition-colors duration-200"
    >
      <div className="flex items-center justify-between bg-white dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0 sticky top-0 z-10 transition-colors duration-200">
        <div className="flex items-center">
          <button
            type="button"
            data-testid="output-tab"
            onClick={() => setActiveTab("output")}
            className={`flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors ${
              activeTab === "output"
                ? "border-blue-500 bg-gray-100 dark:bg-[#252525] text-gray-800 dark:text-gray-200"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#252525] hover:text-gray-900 dark:hover:text-gray-200"
            }`}
          >
            <TerminalIcon size={16} className="text-blue-600 dark:text-blue-400" />
            <span className="text-xs font-semibold uppercase tracking-widest">출력 콘솔</span>
          </button>

          <button
            type="button"
            data-testid="terminal-tab"
            onClick={openTerminalTab}
            className={`flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors ${
              activeTab === "terminal"
                ? "border-green-500 bg-gray-100 dark:bg-[#252525] text-gray-800 dark:text-gray-200"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-[#252525] hover:text-gray-900 dark:hover:text-gray-200"
            }`}
          >
            <Plug size={16} className="text-green-600 dark:text-green-400" />
            <span className="text-xs font-semibold uppercase tracking-widest">터미널</span>
          </button>

          {!isGraphViewerOpen && (
            <button
              onClick={() => setGraphViewerOpen(true)}
              className="flex items-center gap-2 px-4 py-2.5 border-b-2 border-transparent hover:bg-gray-100 dark:hover:bg-[#252525] transition-colors group"
            >
              <Network size={16} className="text-purple-600 dark:text-purple-400 group-hover:text-purple-500 dark:group-hover:text-purple-300" />
              <span className="text-xs font-semibold text-gray-500 dark:text-gray-400 group-hover:text-gray-900 dark:group-hover:text-gray-200 uppercase tracking-widest">파이프라인 뷰어</span>
              <Maximize2 size={12} className="text-gray-400 dark:text-gray-500 group-hover:text-blue-500 dark:group-hover:text-blue-400 ml-1" />
            </button>
          )}
        </div>

        <div className="flex items-center gap-3 px-4">
          {activeTab === "output" ? (
            <>
              <button
                onClick={restartConsole}
                className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                title="콘솔 재시작"
              >
                <RefreshCw size={14} /> 재시작
              </button>
              <div className="w-[1px] h-3.5 bg-gray-300 dark:bg-[#444]" />
              <button
                onClick={clearOutput}
                className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                title="콘솔 지우기"
              >
                <XCircle size={14} /> 지우기
              </button>
            </>
          ) : (
            <>
              <button
                onClick={terminalStatus === "connected" ? restartTerminal : connectTerminal}
                disabled={terminalStatus === "connecting"}
                className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="터미널 연결"
              >
                <RefreshCw size={14} /> {terminalStatus === "connected" ? "재시작" : terminalStatus === "connecting" ? "연결 중" : "연결"}
              </button>
              {terminalStatus === "connected" && (
                <>
                  <div className="w-[1px] h-3.5 bg-gray-300 dark:bg-[#444]" />
                  <button
                    onClick={disconnectTerminal}
                    className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                    title="터미널 연결 종료"
                  >
                    <XCircle size={14} /> 종료
                  </button>
                </>
              )}
              <div className="w-[1px] h-3.5 bg-gray-300 dark:bg-[#444]" />
              <button
                onClick={clearTerminal}
                className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-red-600 dark:hover:text-red-400 transition-colors"
                title="터미널 지우기"
              >
                <XCircle size={14} /> 지우기
              </button>
            </>
          )}
        </div>
      </div>

      <div className="px-4 py-2 border-b border-gray-200 dark:border-[#222] text-[11px] uppercase tracking-widest text-gray-500 dark:text-gray-400 bg-gray-50/80 dark:bg-[#121212] flex items-center justify-between">
        {activeTab === "output" ? (
          <>
            <span>Backend: {backendStatus}</span>
            <span>{isRunning ? "Running" : "Idle"}</span>
          </>
        ) : (
          <>
            <span>Terminal: {terminalStatusLabel[terminalStatus]}</span>
            <span>{language.toUpperCase()} stdin</span>
          </>
        )}
      </div>

      {activeTab === "output" ? (
        <div className="flex-1 p-5 overflow-auto">
          <div className="flex flex-col gap-2">
            {output.map((line, idx) => (
              <div
                key={idx}
                className={`
                  flex leading-relaxed
                  ${line.type === "error" ? "text-red-600 dark:text-red-400" : ""}
                  ${line.type === "success" ? "text-green-600 dark:text-green-400" : ""}
                  ${line.type === "info" ? "text-blue-600 dark:text-blue-300" : ""}
                  ${line.type === "warning" ? "text-yellow-600 dark:text-yellow-400" : ""}
                  ${!["error", "success", "info", "warning"].includes(line.type) ? "text-gray-800 dark:text-gray-300" : ""}
                `}
              >
                {line.type === "error" && <span className="mr-2 text-red-500">x</span>}
                {line.type === "success" && <span className="mr-2 text-green-500">ok</span>}
                {line.type === "info" && <span className="mr-2 text-blue-500">i</span>}
                {line.type === "warning" && <span className="mr-2 text-yellow-500">!</span>}
                <span className="whitespace-pre-wrap">{line.text}</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col">
          <div ref={terminalScrollRef} data-testid="terminal-output" className="flex-1 p-5 overflow-auto">
            <div className="flex flex-col gap-2">
              {terminalLines.map((line, idx) => (
                <div
                  key={idx}
                  className={`
                    leading-relaxed whitespace-pre-wrap
                    ${line.type === "system" ? "text-blue-600 dark:text-blue-300" : ""}
                    ${line.type === "output" ? "text-gray-800 dark:text-gray-300" : ""}
                    ${line.type === "error" ? "text-red-600 dark:text-red-400" : ""}
                  `}
                >
                  {line.text}
                </div>
              ))}
            </div>
          </div>
          <form onSubmit={submitTerminalInput} className="flex items-center gap-3 px-4 py-3 border-t border-gray-200 dark:border-[#333] bg-white dark:bg-[#111]">
            <span className="text-green-600 dark:text-green-400">stdin&gt;</span>
            <input
              data-testid="terminal-input"
              value={terminalInput}
              onChange={(event) => setTerminalInput(event.target.value)}
              disabled={terminalStatus !== "connected"}
              className="flex-1 bg-transparent text-gray-900 dark:text-gray-100 outline-none disabled:cursor-not-allowed disabled:opacity-50"
              placeholder={terminalStatus === "connected" ? "프로그램 stdin으로 보낼 값을 입력하세요" : "터미널 연결 대기 중"}
              autoComplete="off"
              spellCheck={false}
            />
          </form>
        </div>
      )}
    </div>
  );
}
