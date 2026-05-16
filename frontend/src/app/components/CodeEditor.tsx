import Editor, { useMonaco } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";
import { FileCode2, Copy, Check, Loader2, Clock } from "lucide-react";
import { useLocation } from "react-router";
import { useCompilerStore } from "../store/compilerStore";

export function CodeEditor({ onCodeChange }: { onCodeChange?: (code: string) => void }) {
  const monaco = useMonaco();
  const location = useLocation();
  const {
    setSelectedText,
    autoSaveEnabled,
    lastSavedTime,
    saveCode,
    loadCode,
    setCode,
    compileAndStartTerminal,
    compile,
    language,
    setLanguage,
  } = useCompilerStore();
  const [copied, setCopied] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'unsaved'>('saved');
  const editorRef = useRef<any>(null);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isHydratingEditorRef = useRef(false);
  const [hasHydratedEditor, setHasHydratedEditor] = useState(false);
  const [editorReady, setEditorReady] = useState(false);
  const challengeId = location.state?.challenge?.id;

  let defaultCode = `import std.io;

func main() -> u64 {
    var limit: i64 = 100;
    var target: i64 = 84;
    var spf: [101]i64;

    // spf[i] = i의 가장 작은 소인수
    var i: i64 = 0;
    while (i <= limit) {
        spf[i] = 0;
        i = i + 1;
    }

    i = 2;
    while (i <= limit) {
        if (spf[i] == 0) {
            spf[i] = i;

            var j: i64 = i * i;
            while (j <= limit) {
                if (spf[j] == 0) {
                    spf[j] = i;
                }
                j = j + i;
            }
        }
        i = i + 1;
    }

    print("target = ");
    println(target);
    print("factors = ");

    var current: i64 = target;
    var first: i64 = 1;
    while (current > 1) {
        var p: i64 = spf[current];
        if (first == 0) {
            print(" x ");
        }
        print(p);
        first = 0;
        current = current / p;
    }

    return 0;
}
`;

  // 챌린지를 눌러서 왔을 때, 해당하는 기초 뼈대 드를 삽입해줄 수 있습니다.
  if (challengeId === 'c1') {
    defaultCode = `import emitln from std.io;

func main() -> u64 {
    emitln("Hello, World!");
    return 0;
}`;
  } else if (challengeId === 'c2') {
    defaultCode = `import emitln from std.io;

func main() -> u64 {
    var num: i64 = 0;
    // TODO: 입력 처리를 추가한 뒤 짝수면 "Even", 홀수면 "Odd"를 출력하세요.
    if ((num % 2) == 0) {
        emitln("Even");
    } else {
        emitln("Odd");
    }
    return 0;
}`;
  }

  const fileName = language === 'java' ? 'Main.java' : `main.${language === 'python' ? 'py' : language === 'javascript' ? 'js' : language}`;
  const editorLanguage = language === 'c' || language === 'bpp' ? 'cpp' : language;

  const { theme } = useCompilerStore();

  useEffect(() => {
    if (monaco) {
      // Register custom B++ language if needed, for now we'll just map it to C++
      monaco.languages.register({ id: 'bpp' });
      monaco.editor.defineTheme('bpp-dark', {
        base: 'vs-dark',
        inherit: true,
        rules: [],
        colors: {
          'editor.background': '#0d0d0d',
          'editor.lineHighlightBackground': '#1e1e1e',
        }
      });
      monaco.editor.defineTheme('bpp-light', {
        base: 'vs',
        inherit: true,
        rules: [],
        colors: {
          'editor.background': '#ffffff',
          'editor.lineHighlightBackground': '#f3f4f6',
        }
      });
      monaco.editor.setTheme(theme === 'dark' ? 'bpp-dark' : 'bpp-light');
    }
  }, [monaco, theme]);

  const handleCopy = async () => {
    if (editorRef.current) {
      const textToCopy = editorRef.current.getValue();
      try {
        if (navigator?.clipboard?.writeText) {
          await navigator.clipboard.writeText(textToCopy);
        } else {
          throw new Error("Clipboard API not available");
        }
      } catch (err) {
        // Fallback for environments where clipboard API is blocked (like iframes)
        const textArea = document.createElement("textarea");
        textArea.value = textToCopy;
        textArea.style.position = "fixed";  // Avoid scrolling to bottom
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
          document.execCommand('copy');
        } catch (fallbackErr) {
          console.error('Fallback: Oops, unable to copy', fallbackErr);
        }
        document.body.removeChild(textArea);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  // 초기 예제 또는 저장된 코드를 에디터에 주입합니다.
  useEffect(() => {
    if (!editorReady || !editorRef.current) return;

    if (challengeId) {
      setLanguage('bpp');
    }

    const nextCode = challengeId ? defaultCode : loadCode() || defaultCode;

    isHydratingEditorRef.current = true;
    if (editorRef.current.getValue() !== nextCode) {
      editorRef.current.setValue(nextCode);
    }
    if (onCodeChange) onCodeChange(nextCode);
    setCode(nextCode);
    setSaveStatus('saved');
    isHydratingEditorRef.current = false;
    setHasHydratedEditor(true);
  }, [challengeId, defaultCode, editorReady, loadCode, onCodeChange, setCode, setLanguage]);

  // 자동저장 - debounce 방식으로 코드 변경 후 2초 뒤 저장
  useEffect(() => {
    if (!autoSaveEnabled || !hasHydratedEditor) return;

    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }

    if (saveStatus === 'unsaved') {
      setSaveStatus('saving');
      autoSaveTimerRef.current = setTimeout(() => {
        if (editorRef.current) {
          const code = editorRef.current.getValue();
          saveCode(code);
          setSaveStatus('saved');
        }
      }, 2000);
    }

    return () => {
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }
    };
  }, [autoSaveEnabled, saveStatus, saveCode, hasHydratedEditor]);

  // 마지막 저장 시간 포맷팅
  const getLastSavedText = () => {
    if (!lastSavedTime) return '';
    const now = Date.now();
    const diff = now - lastSavedTime;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    
    if (seconds < 5) return '방금 전';
    if (seconds < 60) return `${seconds}초 전`;
    if (minutes < 60) return `${minutes}분 전`;
    return new Date(lastSavedTime).toLocaleTimeString('ko-KR');
  };

  // 키보드 단축키 (Ctrl+S) 처리
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        // Ctrl+S 눌러도 자동저장 시스템 활용
        if (editorRef.current && saveStatus !== 'saved') {
          const code = editorRef.current.getValue();
          saveCode(code);
          setSaveStatus('saved');
        }
      }

      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'B') {
        e.preventDefault();
        void compile();
      }

      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        void compileAndStartTerminal();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [compileAndStartTerminal, compile, saveStatus, saveCode]);

  // 마지막 저장 시간 업데이트 (1초마다)
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    if (!lastSavedTime) return;
    const interval = setInterval(() => {
      forceUpdate(n => n + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [lastSavedTime]);

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#0d0d0d] relative group transition-colors duration-200">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shadow-sm shrink-0 transition-colors duration-200">
        <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
          <FileCode2 size={16} className="text-blue-500" />
          <span className="text-xs font-mono tracking-wider text-gray-700 dark:text-gray-300">{fileName}</span>
        </div>
        
        <button 
          onClick={handleCopy}
          className="p-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#2d2d2d] rounded-md transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
          title="코드 복사"
        >
          {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
        </button>
      </div>

      <div className="flex-1 w-full pt-2 bg-white dark:bg-transparent transition-colors duration-200">
        <Editor
          height="100%"
          language={editorLanguage}
          defaultValue={defaultCode}
          theme={theme === 'dark' ? "bpp-dark" : "bpp-light"}
          onMount={(editor) => {
            editorRef.current = editor;
            setEditorReady(true);
            editor.onDidChangeCursorSelection((e: any) => {
              const selection = e.selection;
              const model = editor.getModel();
              if (model) {
                const selectedStr = model.getValueInRange(selection);
                setSelectedText(selectedStr);
              }
            });
          }}
          onChange={(value) => {
            if (isHydratingEditorRef.current) {
              return;
            }
            const nextCode = value || "";
            onCodeChange && onCodeChange(nextCode);
            setCode(nextCode);
            setSaveStatus('unsaved');
          }}
          options={{
            minimap: { enabled: false },
            fontSize: 14,
            fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
            lineHeight: 24,
            padding: { top: 8, bottom: 8 },
            scrollBeyondLastLine: false,
            smoothScrolling: true,
            cursorBlinking: "smooth",
            cursorSmoothCaretAnimation: "on",
            formatOnPaste: true,
            scrollbar: {
              verticalScrollbarSize: 10,
              horizontalScrollbarSize: 10,
            }
          }}
        />
      </div>

      {/* 저장 상태 표시 바 */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-[#1e1e1e] border-t border-gray-200 dark:border-[#333] shadow-sm shrink-0 transition-colors duration-200">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
            {saveStatus === 'saving' ? (
              <>
                <Loader2 size={14} className="text-blue-500 animate-spin" />
                <span className="text-xs font-mono text-blue-500">저장 중...</span>
              </>
            ) : saveStatus === 'saved' ? (
              <>
                <Check size={14} className="text-green-500" />
                <span className="text-xs font-mono text-green-600 dark:text-green-400">모든 변경사항 저장됨</span>
              </>
            ) : (
              <>
                <Clock size={14} className="text-yellow-500" />
                <span className="text-xs font-mono text-yellow-600 dark:text-yellow-400">변경사항 있음</span>
              </>
            )}
          </div>
          {lastSavedTime && saveStatus === 'saved' && (
            <span className="text-xs text-gray-400 dark:text-gray-500">
              • {getLastSavedText()}
            </span>
          )}
        </div>
        
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400 font-mono">
            자동저장 활성화
          </span>
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
        </div>
      </div>
    </div>
  );
}
