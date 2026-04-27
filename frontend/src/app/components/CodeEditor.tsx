import Editor, { useMonaco } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";
import { FileCode2, Copy, Check, BookOpen, ChevronDown, ChevronUp, Target, Send, Award, Loader2, Clock, CheckCircle, XCircle } from "lucide-react";
import { useLocation } from "react-router";
import { useCompilerStore } from "../store/compilerStore";
import { judgeCode } from "../services/judgeApi";
import type { JudgeSummary } from "../services/judgeApi";
import { submitLeaderboardScore } from "../services/problemApi";
import { getLeaderboardProfile } from "../services/leaderboardProfile";

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
  const [isChallengeOpen, setIsChallengeOpen] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [score, setScore] = useState<number | null>(null);
  const [earnedPoints, setEarnedPoints] = useState<number | null>(null);
  const [judgeResult, setJudgeResult] = useState<JudgeSummary | null>(null);
  const [isJudgeDetailOpen, setIsJudgeDetailOpen] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'unsaved'>('saved');
  const editorRef = useRef<any>(null);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isHydratingEditorRef = useRef(false);
  const [hasHydratedEditor, setHasHydratedEditor] = useState(false);
  const [editorReady, setEditorReady] = useState(false);
  
  // URL 상태에서 challenge 전체 정보를 받아옵니다.
  const challenge = location.state?.challenge;
  const challengeId = challenge?.id;

  const handleSubmitChallenge = async () => {
    if (!editorRef.current) return;
    setIsSubmitting(true);
    setScore(null);
    setEarnedPoints(null);
    setJudgeResult(null);

    try {
      const code = editorRef.current.getValue();
      const testCases = challenge?.testCases ?? [
        { input: "", expectedOutput: challenge?.expectedOutput ?? "" }
      ];
      const result = await judgeCode(code, testCases);
      setJudgeResult(result);
      setIsJudgeDetailOpen(true);

      const calculatedScore = Math.round((result.passedCount / result.totalCount) * 100);
      setScore(calculatedScore);

      let points = 20;
      if (challenge?.difficulty === 'intermediate') points = 50;
      if (challenge?.difficulty === 'advanced') points = 100;

      let awardedPoints = 0;
      if (calculatedScore === 100 && challengeId) {
        const normalizedChallengeId = String(challengeId);
        const profile = getLeaderboardProfile();

        try {
          const scoreResult = await submitLeaderboardScore({
            username: profile.name,
            points,
            challengeId: normalizedChallengeId,
            avatarUrl: profile.avatar,
          });
          awardedPoints = scoreResult.awardedPoints;
        } catch (error) {
          console.error('Failed to submit leaderboard score', error);
        }
      }

      setEarnedPoints(awardedPoints);
    } catch {
      setScore(0);
      setEarnedPoints(0);
    } finally {
      setIsSubmitting(false);
    }
  };

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

      {/* 챌���지가 있을 경우 표시되는 접이식 패널 */}
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

              {/* 채점 상세 결과 (접기/펼치기) */}
              {judgeResult && (
                <div className="border-t border-gray-200 dark:border-[#333] mt-2 pt-1">
                  <button
                    onClick={() => setIsJudgeDetailOpen(!isJudgeDetailOpen)}
                    className="flex items-center justify-between w-full py-2 hover:opacity-80 transition-opacity"
                  >
                    <span className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      채점 상세 ({judgeResult.passedCount}/{judgeResult.totalCount} 통과)
                    </span>
                    {isJudgeDetailOpen ? <ChevronUp size={14} className="text-gray-500" /> : <ChevronDown size={14} className="text-gray-500" />}
                  </button>

                  {isJudgeDetailOpen && (
                    <div className="flex flex-col gap-2 pb-1 animate-in slide-in-from-top-2 fade-in duration-200">
                      {judgeResult.results.map((r, idx) => (
                        <div key={idx} className={`p-2.5 rounded border ${
                          r.passed ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5"
                        }`}>
                          <div className="flex items-center gap-2 mb-1.5">
                            {r.passed ? (
                              <CheckCircle size={13} className="text-green-400" />
                            ) : (
                              <XCircle size={13} className="text-red-400" />
                            )}
                            <span className="text-xs font-semibold text-gray-300 dark:text-gray-300">테스트 #{idx + 1}</span>
                            <span className="text-[10px] text-gray-500 ml-auto">{r.executionTime}ms</span>
                          </div>
                          <div className="grid grid-cols-3 gap-2 text-[11px]">
                            <div>
                              <p className="text-gray-500 mb-0.5">입력</p>
                              <code className="block bg-white/5 dark:bg-[#0d0d0d] rounded px-1.5 py-1 text-gray-400 whitespace-pre-wrap">{r.input || "(없음)"}</code>
                            </div>
                            <div>
                              <p className="text-gray-500 mb-0.5">기대 출력</p>
                              <code className="block bg-white/5 dark:bg-[#0d0d0d] rounded px-1.5 py-1 text-green-400 whitespace-pre-wrap">{r.expected}</code>
                            </div>
                            <div>
                              <p className="text-gray-500 mb-0.5">실제 출력</p>
                              <code className={`block bg-white/5 dark:bg-[#0d0d0d] rounded px-1.5 py-1 whitespace-pre-wrap ${r.passed ? "text-green-400" : "text-red-400"}`}>{r.actual || "(없음)"}</code>
                            </div>
                          </div>
                          {r.error && <p className="text-[11px] text-red-400 mt-1">오류: {r.error}</p>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      
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
