import { useEffect, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { useLocation } from "react-router";
import { ChallengePanel } from "../components/ChallengePanel";
import { CodeEditor } from "../components/CodeEditor";
import { OutputConsole } from "../components/OutputConsole";
import { CompilerGraphViewer } from "../components/CompilerGraphViewer";
import { useCompilerStore } from "../store/compilerStore";
import type { ContestProblemDetail } from "../services/contestApi";

type MobilePanel = "problem" | "editor" | "console" | "graph";

function useMobileLayout() {
  const [isMobile, setIsMobile] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(max-width: 767px)").matches : false,
  );

  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setIsMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isMobile;
}

export function IDE({ contestProblem }: { contestProblem?: ContestProblemDetail } = {}) {
  const location = useLocation();
  const { code, setCode, isGraphViewerOpen } = useCompilerStore();
  const challenge = contestProblem ?? location.state?.challenge;
  const isMobile = useMobileLayout();
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>("editor");

  useEffect(() => {
    if (isMobile && isGraphViewerOpen) setMobilePanel("graph");
  }, [isGraphViewerOpen, isMobile]);

  if (isMobile) {
    const tabs: { id: MobilePanel; label: string }[] = [
      ...(challenge ? [{ id: "problem" as const, label: "문제" }] : []),
      { id: "editor", label: "코드" },
      { id: "console", label: "실행 결과" },
      { id: "graph", label: "그래프" },
    ];

    const selectPanel = (panel: MobilePanel) => {
      if (panel === "graph" && !isGraphViewerOpen) useCompilerStore.getState().setGraphViewerOpen(true);
      setMobilePanel(panel);
    };

    return (
      <div className="flex h-full min-h-0 w-full flex-col bg-white dark:bg-[#0d0d0d]">
        <div
          role="tablist"
          aria-label="IDE 패널"
          className="grid shrink-0 border-b border-gray-200 bg-white dark:border-[#333] dark:bg-[#1e1e1e]"
          style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}
        >
          {tabs.map((tab) => (
            <button
              key={tab.id}
              id={`mobile-${tab.id}-tab`}
              type="button"
              role="tab"
              aria-selected={mobilePanel === tab.id}
              aria-controls={`mobile-${tab.id}-panel`}
              tabIndex={mobilePanel === tab.id ? 0 : -1}
              onClick={() => selectPanel(tab.id)}
              onKeyDown={(event) => {
                const currentIndex = tabs.findIndex(({ id }) => id === tab.id);
                const nextIndex = event.key === "ArrowRight"
                  ? (currentIndex + 1) % tabs.length
                  : event.key === "ArrowLeft"
                    ? (currentIndex - 1 + tabs.length) % tabs.length
                    : -1;
                if (nextIndex >= 0) {
                  event.preventDefault();
                  const nextTab = tabs[nextIndex];
                  selectPanel(nextTab.id);
                  document.getElementById(`mobile-${nextTab.id}-tab`)?.focus();
                }
              }}
              className={`min-w-0 px-2 py-3 text-xs font-semibold focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-blue-500 ${
                mobilePanel === tab.id
                  ? "border-b-2 border-blue-500 text-blue-600 dark:text-blue-400"
                  : "text-gray-500 dark:text-gray-400"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="relative min-h-0 flex-1">
          {challenge && (
            <div id="mobile-problem-panel" role="tabpanel" aria-labelledby="mobile-problem-tab" hidden={mobilePanel !== "problem"} className="h-full overflow-auto">
              <ChallengePanel challenge={challenge} code={code} contest={contestProblem?.contest} />
            </div>
          )}
          <div id="mobile-editor-panel" role="tabpanel" aria-labelledby="mobile-editor-tab" hidden={mobilePanel !== "editor"} className="h-full">
            <CodeEditor onCodeChange={setCode} />
          </div>
          <div id="mobile-console-panel" role="tabpanel" aria-labelledby="mobile-console-tab" hidden={mobilePanel !== "console"} className="h-full">
            <OutputConsole />
          </div>
          <div id="mobile-graph-panel" role="tabpanel" aria-labelledby="mobile-graph-tab" hidden={mobilePanel !== "graph"} className="h-full">
            {isGraphViewerOpen ? <CompilerGraphViewer code={code} /> : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full bg-white dark:bg-[#0d0d0d] transition-colors duration-200">
      <PanelGroup direction="horizontal" className="w-full h-full" id="main-horizontal-group">
        {challenge && (
          <>
            <Panel defaultSize={32} minSize={20} id="challenge-panel" order={1}>
              <ChallengePanel challenge={challenge} code={code} contest={contestProblem?.contest} />
            </Panel>

            <PanelResizeHandle className="w-2 bg-gray-100 dark:bg-[#1e1e1e] border-x border-gray-200 dark:border-[#333] hover:bg-blue-100 dark:hover:bg-blue-600/50 transition-colors cursor-col-resize flex flex-col items-center justify-center relative z-10" id="challenge-horizontal-resize">
              <div className="h-12 w-0.5 bg-gray-300 dark:bg-gray-500 rounded-full" />
            </PanelResizeHandle>
          </>
        )}

        {/* 메인 패널: 에디터 및 콘솔 */}
        <Panel defaultSize={challenge ? (isGraphViewerOpen ? 43 : 68) : (isGraphViewerOpen ? 75 : 100)} minSize={30} id="editor-console-panel" order={challenge ? 2 : 1}>
          <PanelGroup direction="vertical" className="w-full h-full" id="editor-vertical-group">
            <Panel defaultSize={70} minSize={20} id="editor-panel" order={1}>
              <CodeEditor onCodeChange={setCode} />
            </Panel>
            
            <PanelResizeHandle className="h-2 bg-gray-100 dark:bg-[#1e1e1e] border-y border-gray-200 dark:border-[#333] hover:bg-blue-100 dark:hover:bg-blue-600/50 transition-colors cursor-row-resize flex items-center justify-center relative z-10" id="editor-vertical-resize">
              <div className="w-12 h-0.5 bg-gray-300 dark:bg-gray-500 rounded-full" />
            </PanelResizeHandle>
            
            <Panel defaultSize={30} minSize={10} id="console-panel" order={2}>
              <OutputConsole />
            </Panel>
          </PanelGroup>
        </Panel>

        {isGraphViewerOpen && (
          <>
            <PanelResizeHandle className="w-2 bg-gray-100 dark:bg-[#1e1e1e] border-x border-gray-200 dark:border-[#333] hover:bg-blue-100 dark:hover:bg-blue-600/50 transition-colors cursor-col-resize flex flex-col items-center justify-center relative z-10" id="main-horizontal-resize">
              <div className="h-12 w-0.5 bg-gray-300 dark:bg-gray-500 rounded-full" />
            </PanelResizeHandle>

            {/* 오른쪽 패널: AST 및 SSA 파이프라인 그래프 */}
            <Panel defaultSize={25} minSize={20} id="graph-viewer-panel" order={challenge ? 3 : 2}>
              <CompilerGraphViewer code={code} />
            </Panel>
          </>
        )}
      </PanelGroup>
    </div>
  );
}
