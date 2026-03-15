import { useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { CodeEditor } from "../components/CodeEditor";
import { OutputConsole } from "../components/OutputConsole";
import { CompilerGraphViewer } from "../components/CompilerGraphViewer";
import { useCompilerStore } from "../store/compilerStore";

export function IDE() {
  const [code, setCode] = useState("");
  const { isGraphViewerOpen } = useCompilerStore();

  return (
    <div className="relative w-full h-full bg-white dark:bg-[#0d0d0d] transition-colors duration-200">
      <PanelGroup direction="horizontal" className="w-full h-full" id="main-horizontal-group">
        {/* 왼쪽 패널: 기존 에디터 및 콘솔 */}
        <Panel defaultSize={isGraphViewerOpen ? 75 : 100} minSize={30} id="editor-console-panel" order={1}>
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
            <Panel defaultSize={25} minSize={20} id="graph-viewer-panel" order={2}>
              <CompilerGraphViewer code={code} />
            </Panel>
          </>
        )}
      </PanelGroup>
    </div>
  );
}
