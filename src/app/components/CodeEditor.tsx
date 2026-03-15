import Editor, { useMonaco } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";
import { FileCode2, Copy, Check, BookOpen, ChevronDown, ChevronUp, Target, Send, Award, Loader2 } from "lucide-react";
import { useLocation } from "react-router";
import { useCompilerStore } from "../store/compilerStore";

export function CodeEditor({ onCodeChange }: { onCodeChange?: (code: string) => void }) {
  const monaco = useMonaco();
  const location = useLocation();
  const { setSelectedText } = useCompilerStore();
  const [copied, setCopied] = useState(false);
  const [isChallengeOpen, setIsChallengeOpen] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const [earnedPoints, setEarnedPoints] = useState<number | null>(null);
  const editorRef = useRef<any>(null);
  
  // URL 상태에서 challenge 전체 정보를 받아옵니다.
  const challenge = location.state?.challenge;
  const challengeId = challenge?.id;

  const handleSubmitChallenge = () => {
    if (!editorRef.current) return;
    setIsSubmitting(true);
    setScore(null);
    setEarnedPoints(null);
    
    // 채점 과정을 시뮬레이션 (1.5초 대기)
    setTimeout(() => {
      setIsSubmitting(false);
      setScore(100); // 100점 만점
      
      // 난이도에 따른 포인트 차등 지급
      let points = 20;
      if (challenge?.difficulty === 'intermediate') points = 50;
      if (challenge?.difficulty === 'advanced') points = 100;
      
      setEarnedPoints(points);
    }, 1500);
  };

  let defaultCode = `func main(argc: i64, argv: *u64) -> i64 {
    var sum_for: i64 = 0;

    for (var i: i64 = 0; i < 6; i = i + 1) {
        sum_for = sum_for + i;
    }

    return 0;
}
`;

  // 챌린지를 눌러서 왔을 때, 해당하는 기초 뼈대 ��드를 삽입해줄 수 있습니다.
  if (challengeId === 'c1') {
    defaultCode = `// 챌린지: B++로 "Hello, World!" 출력하기
#include <iostream>

int main() {
    // 여기에 코드를 작성하세요
    
    return 0;
}`;
  } else if (challengeId === 'c2') {
    defaultCode = `// 챌린지: 홀수와 짝수
#include <iostream>

int main() {
    int num;
    std::cin >> num;
    // 짝수면 "Even", 홀수면 "Odd"를 출력하세요
    
    return 0;
}`;
  }

  // 초기 코드 설정
  useEffect(() => {
    if (onCodeChange) onCodeChange(defaultCode);
  }, [defaultCode, onCodeChange]);

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

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#0d0d0d] relative group transition-colors duration-200">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shadow-sm shrink-0 transition-colors duration-200">
        <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400">
          <FileCode2 size={16} className="text-blue-500" />
          <span className="text-xs font-mono tracking-wider text-gray-700 dark:text-gray-300">main.bpp</span>
        </div>
        
        <button 
          onClick={handleCopy}
          className="p-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#2d2d2d] rounded-md transition-colors opacity-0 group-hover:opacity-100 focus:opacity-100"
          title="코드 복사"
        >
          {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
        </button>
      </div>

      {/* 챌린지가 있을 경우 표시되는 접이식 패널 */}
      {challenge && (
        <div className="flex flex-col bg-gray-50 dark:bg-[#161616] border-b border-gray-200 dark:border-[#333] shrink-0 transition-colors duration-200">
          <button
            onClick={() => setIsChallengeOpen(!isChallengeOpen)}
            className="flex items-center justify-between px-4 py-2.5 hover:bg-gray-100 dark:hover:bg-[#1a1a1a] transition-colors focus:outline-none"
          >
            <div className="flex items-center gap-2">
              <BookOpen size={16} className="text-blue-500 dark:text-blue-400" />
              <span className="text-sm font-bold text-gray-800 dark:text-gray-200">현재 챌린지: {challenge.title}</span>
            </div>
            {isChallengeOpen ? (
              <ChevronUp size={16} className="text-gray-500" />
            ) : (
              <ChevronDown size={16} className="text-gray-500" />
            )}
          </button>
          
          {isChallengeOpen && (
            <div className="px-4 pb-4 pt-1 flex flex-col gap-3 animate-in slide-in-from-top-2 fade-in duration-200">
              <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                {challenge.description}
              </p>
              <div>
                <div className="flex items-center gap-1.5 mb-1.5 text-xs font-bold text-gray-600 dark:text-gray-300 uppercase tracking-wider">
                  <Target size={14} className="text-green-600 dark:text-green-400" />
                  기대 출력
                </div>
                <div className="bg-white dark:bg-[#0d0d0d] border border-gray-200 dark:border-[#333] rounded p-2.5 font-mono text-xs text-green-600 dark:text-green-400 break-words">
                  {challenge.expectedOutput}
                </div>
              </div>

              {/* 채점 결과 및 제출 버튼 */}
              <div className="mt-1 flex flex-col sm:flex-row items-start sm:items-center gap-4">
                {score !== null && (
                  <div className={`flex items-center gap-4 px-3 py-2 rounded-lg border ${score === 100 ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mb-0.5">채점 결과</span>
                      <span className={`text-sm font-bold leading-none ${score === 100 ? 'text-green-400' : 'text-red-400'}`}>
                        {score} <span className="text-xs font-medium opacity-70">/ 100 점</span>
                      </span>
                    </div>
                    <div className="w-px h-6 bg-[#333]"></div>
                    <div className="flex flex-col">
                      <span className="text-[10px] text-gray-500 font-bold uppercase tracking-wider mb-0.5">획득 포인트</span>
                      <span className="text-sm font-bold text-yellow-400 flex items-center gap-1 leading-none">
                        <Award size={14} className="text-yellow-500" />
                        +{earnedPoints} <span className="text-xs font-medium opacity-70">XP</span>
                      </span>
                    </div>
                  </div>
                )}

                <button 
                  onClick={handleSubmitChallenge}
                  disabled={isSubmitting}
                  className={`flex items-center justify-center gap-2 px-5 py-2 text-sm font-semibold rounded-lg transition-colors ml-auto
                    ${isSubmitting 
                      ? 'bg-[#333] text-gray-500 cursor-not-allowed' 
                      : 'bg-blue-600 hover:bg-blue-500 text-white'}`}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      채점 중...
                    </>
                  ) : (
                    <>
                      <Send size={16} />
                      제출하기
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
      
      <div className="flex-1 w-full pt-2 bg-white dark:bg-transparent transition-colors duration-200">
        <Editor
          height="100%"
          defaultLanguage="cpp"
          defaultValue={defaultCode}
          theme={theme === 'dark' ? "bpp-dark" : "bpp-light"}
          onMount={(editor) => {
            editorRef.current = editor;
            editor.onDidChangeCursorSelection((e: any) => {
              const selection = e.selection;
              const model = editor.getModel();
              if (model) {
                const selectedStr = model.getValueInRange(selection);
                setSelectedText(selectedStr);
              }
            });
          }}
          onChange={(value) => onCodeChange && onCodeChange(value || "")}
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
    </div>
  );
}
