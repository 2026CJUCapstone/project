import { Terminal as TerminalIcon, XCircle, RefreshCw, Network, Maximize2 } from "lucide-react";
import { useCompilerStore } from "../store/compilerStore";

export function OutputConsole() {
  const { isGraphViewerOpen, setGraphViewerOpen, output, clearOutput, restartConsole, backendStatus, isRunning } = useCompilerStore();

  return (
    <div className="flex flex-col h-full bg-gray-50 dark:bg-[#0d0d0d] font-mono text-sm shadow-[inset_0_2px_10px_rgba(0,0,0,0.05)] dark:shadow-[inset_0_2px_10px_rgba(0,0,0,0.5)] transition-colors duration-200">
      <div className="flex items-center justify-between bg-white dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0 sticky top-0 z-10 transition-colors duration-200">
        <div className="flex items-center">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b-2 border-blue-500 bg-gray-100 dark:bg-[#252525] transition-colors duration-200">
            <TerminalIcon size={16} className="text-blue-600 dark:text-blue-400" />
            <span className="text-xs font-semibold text-gray-800 dark:text-gray-200 uppercase tracking-widest">출력 콘솔</span>
          </div>
          
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
        </div>
      </div>

      <div className="px-4 py-2 border-b border-gray-200 dark:border-[#222] text-[11px] uppercase tracking-widest text-gray-500 dark:text-gray-400 bg-gray-50/80 dark:bg-[#121212] flex items-center justify-between">
        <span>Backend: {backendStatus}</span>
        <span>{isRunning ? 'Running' : 'Idle'}</span>
      </div>
      
      <div className="flex-1 p-5 overflow-auto">
        <div className="flex flex-col gap-2">
          {output.map((line, idx) => (
            <div 
              key={idx} 
              className={`
                flex leading-relaxed
                ${line.type === 'error' ? 'text-red-600 dark:text-red-400' : ''}
                ${line.type === 'success' ? 'text-green-600 dark:text-green-400' : ''}
                ${line.type === 'info' ? 'text-blue-600 dark:text-blue-300' : ''}
                ${line.type === 'input' ? 'text-gray-500 dark:text-gray-400 animate-pulse' : ''}
                ${!['error', 'success', 'info', 'input'].includes(line.type) ? 'text-gray-800 dark:text-gray-300' : ''}
              `}
            >
              {line.type === 'error' && <span className="mr-2 text-red-500">✖</span>}
              {line.type === 'success' && <span className="mr-2 text-green-500">✓</span>}
              {line.type === 'info' && <span className="mr-2 text-blue-500">ℹ</span>}
              <span className="whitespace-pre-wrap">{line.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}