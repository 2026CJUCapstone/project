import { useMemo } from 'react';
import { Network, GitBranch, GitMerge, FileCode2, Minus } from 'lucide-react';
import { useCompilerStore } from '../store/compilerStore';

export function CompilerGraphViewer({ code }: { code: string }) {
  const { setGraphViewerOpen, activeGraphTab, setActiveGraphTab, selectedText } = useCompilerStore();

  const hasIf = code.includes('if');
  const hasFor = code.includes('for') || code.includes('while');
  const hasPrint = code.includes('cout') || code.includes('print');
  
  const isIfSelected = selectedText.includes('if') || selectedText.includes('else');
  const isForSelected = selectedText.includes('for') || selectedText.includes('while');
  const isPrintSelected = selectedText.includes('cout') || selectedText.includes('print');
  const isMainSelected = selectedText.includes('main') || (selectedText.trim().length > 0 && !isIfSelected && !isForSelected && !isPrintSelected);

  const getStyle = (isSelected: boolean, fill: string, border: string, textCol: string) => {
    if (isSelected && selectedText.trim().length > 0) {
      return `fillcolor="#fde047", color="#ca8a04", fontcolor="#000000", penwidth=3`;
    }
    return `fillcolor="${fill}", color="${border}", fontcolor="${textCol}", penwidth=1`;
  };

  const graphvizDot = useMemo(() => {
    const commonStyles = `
    rankdir=TB;
    compound=true;
    fontname="Helvetica, Arial, sans-serif";
    node [fontname="Helvetica, Arial, sans-serif", fontsize=11, margin=0.2];
    edge [fontname="Helvetica, Arial, sans-serif", fontsize=9, color="#666666"];
    `;

    if (activeGraphTab === 'AST') {
      return `
      digraph AST_Graph {
          ${commonStyles}
          subgraph cluster_AST {
              label = "1. AST (Abstract Syntax Tree)";
              style = "filled, rounded";
              color = "#2c2c2c";
              fillcolor = "#1e1e1e";
              fontcolor = "#ffb74d";
              fontsize = 14;
              node [shape=ellipse, fillcolor="#422910", color="#F57C00", fontcolor="#ffffff", style="filled"];

              AST_Root [label="Program"];
              AST_Main [label="FunctionDecl\\nmain()", ${getStyle(isMainSelected, "#422910", "#F57C00", "#ffffff")}];
              
              AST_Root -> AST_Main;
              
              ${hasIf ? `
              AST_If [label="If Statement", ${getStyle(isIfSelected, "#422910", "#F57C00", "#ffffff")}];
              AST_Main -> AST_If;
              AST_Cond [label="Condition", ${getStyle(isIfSelected, "#422910", "#F57C00", "#ffffff")}];
              AST_True [label="True Body", ${getStyle(isIfSelected, "#422910", "#F57C00", "#ffffff")}];
              AST_If -> AST_Cond;
              AST_If -> AST_True;
              ` : `AST_Stmt [label="Statement List", ${getStyle(isMainSelected, "#422910", "#F57C00", "#ffffff")}]; AST_Main -> AST_Stmt;`}
              
              ${hasFor ? `
              AST_Loop [label="Loop Statement", ${getStyle(isForSelected, "#422910", "#F57C00", "#ffffff")}];
              AST_Main -> AST_Loop;
              ` : ''}
              
              ${hasPrint ? `
              AST_Print [label="FunctionCall\\nprint/cout", ${getStyle(isPrintSelected, "#422910", "#F57C00", "#ffffff")}];
              ${hasIf ? 'AST_True -> AST_Print;' : 'AST_Stmt -> AST_Print;'}
              ` : ''}
          }
      }
      `;
    }

    if (activeGraphTab === 'SSA') {
      return `
      digraph SSA_Graph {
          ${commonStyles}
          subgraph cluster_SSA {
              label = "2. SSA (Static Single Assignment) CFG";
              style = "filled, rounded";
              color = "#2c2c2c";
              fillcolor = "#1e1e1e";
              fontcolor = "#4db6ac";
              fontsize = 14;
              node [shape=record, fillcolor="#103b36", color="#00796B", fontcolor="#ffffff", style="filled"];

              SSA_Entry [label="{ Block 0 (Entry) | var_1 = init \\l ${hasIf ? '| branch B1, B2 \\l' : '| jump B1 \\l'} }", ${getStyle(isMainSelected, "#103b36", "#00796B", "#ffffff")}];
              
              ${hasIf ? `
              SSA_B1 [label="{ Block 1 (True) | var_2 = expr \\l | jump B3 \\l }", ${getStyle(isIfSelected, "#103b36", "#00796B", "#ffffff")}];
              SSA_B2 [label="{ Block 2 (False) | var_3 = expr \\l | jump B3 \\l }", ${getStyle(isIfSelected, "#103b36", "#00796B", "#ffffff")}];
              SSA_B3 [label="{ Block 3 (Merge) | var_4 = Φ(var_2, var_3) \\l | return 0 \\l }", ${getStyle(isMainSelected, "#103b36", "#00796B", "#ffffff")}];
              
              SSA_Entry -> SSA_B1 [label=" True", fontcolor="#81c784", color="#81c784"];
              SSA_Entry -> SSA_B2 [label=" False", fontcolor="#e57373", color="#e57373"];
              SSA_B1 -> SSA_B3 [color="#64b5f6"];
              SSA_B2 -> SSA_B3 [color="#64b5f6"];
              ` : `
              SSA_B1 [label="{ Block 1 (Body) | var_2 = expr \\l | return 0 \\l }", ${getStyle(isMainSelected, "#103b36", "#00796B", "#ffffff")}];
              SSA_Entry -> SSA_B1 [color="#64b5f6"];
              `}
          }
      }
      `;
    }

    if (activeGraphTab === 'IR') {
      return `
      digraph IR_Graph {
          ${commonStyles}
          subgraph cluster_IR {
              label = "3. IR (Intermediate Representation)";
              style = "filled, rounded";
              color = "#2c2c2c";
              fillcolor = "#1e1e1e";
              fontcolor = "#ba68c8";
              fontsize = 14;
              node [shape=box, fillcolor="#3a1c40", color="#8e24aa", fontcolor="#ffffff", style="filled"];

              IR_1 [label="%1 = alloca i32, align 4", ${getStyle(isMainSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              IR_2 [label="store i32 0, i32* %1, align 4", ${getStyle(isMainSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              
              ${hasIf ? `
              IR_3 [label="%2 = icmp sgt i32 %1, 0", ${getStyle(isIfSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              IR_4 [label="br i1 %2, label %true_blk, label %false_blk", ${getStyle(isIfSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              IR_5 [label="true_blk:", ${getStyle(isIfSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              IR_6 [label="  %3 = add i32 %1, 1", ${getStyle(isIfSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              
              IR_1 -> IR_2;
              IR_2 -> IR_3;
              IR_3 -> IR_4;
              IR_4 -> IR_5 [label=" true"];
              IR_5 -> IR_6;
              ` : `
              IR_3 [label="%2 = add i32 %1, 1", ${getStyle(isMainSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              IR_4 [label="ret i32 0", ${getStyle(isMainSelected, "#3a1c40", "#8e24aa", "#ffffff")}];
              
              IR_1 -> IR_2;
              IR_2 -> IR_3;
              IR_3 -> IR_4;
              `}
          }
      }
      `;
    }

    // ASM
    return `
    digraph ASM_Graph {
        ${commonStyles}
        subgraph cluster_ASM {
            label = "4. ASM (Assembly Code)";
            style = "filled, rounded";
            color = "#2c2c2c";
            fillcolor = "#1e1e1e";
            fontcolor = "#e57373";
            fontsize = 14;
            node [shape=note, fillcolor="#401c1c", color="#e53935", fontcolor="#ffffff", style="filled"];

            ASM_1 [label="push rbp\\nmov rbp, rsp\\nsub rsp, 16", ${getStyle(isMainSelected, "#401c1c", "#e53935", "#ffffff")}];
            
            ${hasIf ? `
            ASM_2 [label="cmp dword ptr [rbp - 4], 0\\njle .LBB0_2", ${getStyle(isIfSelected, "#401c1c", "#e53935", "#ffffff")}];
            ASM_3 [label=".LBB0_1:\\nmov eax, 1\\njmp .LBB0_3", ${getStyle(isIfSelected, "#401c1c", "#e53935", "#ffffff")}];
            ASM_4 [label=".LBB0_2:\\nmov eax, 0", ${getStyle(isIfSelected, "#401c1c", "#e53935", "#ffffff")}];
            
            ASM_1 -> ASM_2;
            ASM_2 -> ASM_3 [label=" > 0"];
            ASM_2 -> ASM_4 [label=" <= 0"];
            ` : `
            ASM_2 [label="mov dword ptr [rbp - 4], 0", ${getStyle(isMainSelected, "#401c1c", "#e53935", "#ffffff")}];
            ASM_3 [label="mov eax, 0\\nadd rsp, 16\\npop rbp\\nret", ${getStyle(isMainSelected, "#401c1c", "#e53935", "#ffffff")}];
            
            ASM_1 -> ASM_2;
            ASM_2 -> ASM_3;
            `}
        }
    }
    `;
  }, [hasIf, hasFor, hasPrint, activeGraphTab, selectedText, isIfSelected, isForSelected, isPrintSelected, isMainSelected]);

  const imageUrl = `https://quickchart.io/graphviz?graph=${encodeURIComponent(graphvizDot)}`;

  const tabs = ['AST', 'SSA', 'IR', 'ASM'] as const;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-[#121212] border-l border-gray-200 dark:border-[#333] transition-colors duration-200">
      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-[#1e1e1e] border-b border-gray-200 dark:border-[#333] shrink-0 transition-colors duration-200">
        <div className="flex items-center gap-2">
          <Network size={18} className="text-purple-500 dark:text-purple-400" />
          <h2 className="text-sm font-bold text-gray-800 dark:text-gray-200 uppercase tracking-wider">Compiler Pipeline Viewer</h2>
        </div>
        <button 
          onClick={() => setGraphViewerOpen(false)}
          className="p-1 hover:bg-gray-200 dark:hover:bg-[#333] text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white rounded transition-colors"
          title="최소화"
        >
          <Minus size={18} />
        </button>
      </div>
      
      <div className="flex items-center border-b border-gray-200 dark:border-[#333] bg-gray-50 dark:bg-[#1a1a1a] px-2 pt-2 transition-colors duration-200">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveGraphTab(tab)}
            className={`px-4 py-2 text-xs font-semibold uppercase tracking-wider border-b-2 transition-colors ${
              activeGraphTab === tab 
                ? 'border-blue-500 text-blue-600 dark:text-blue-400' 
                : 'border-transparent text-gray-500 hover:text-gray-800 dark:hover:text-gray-300'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>
      
      <div className="flex-1 overflow-auto p-4 flex flex-col items-center">
        <div className="w-full max-w-2xl bg-white dark:bg-[#0d0d0d] rounded-lg border border-gray-200 dark:border-[#333] p-4 shadow-md dark:shadow-xl mb-4 transition-colors duration-200">
          <div className="flex items-center gap-2 mb-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-widest">
            <FileCode2 size={14} className="text-blue-500 dark:text-blue-400" />
            Live {activeGraphTab} Graph
          </div>
          
          <div className="w-full min-h-[400px] flex items-center justify-center bg-gray-50 dark:bg-[#1a1a1a] rounded border border-gray-200 dark:border-[#222] p-4 transition-colors duration-200">
            <img 
              key={activeGraphTab}
              src={imageUrl} 
              alt={`Compiler ${activeGraphTab} Graph`} 
              className="max-w-full h-auto object-contain drop-shadow-sm dark:drop-shadow-lg transition-opacity duration-300"
              loading="lazy"
            />
          </div>
        </div>

        <div className="w-full max-w-2xl text-xs text-gray-600 dark:text-gray-500 space-y-2 leading-relaxed p-4 bg-gray-50 dark:bg-[#1a1a1a] rounded-lg border border-gray-200 dark:border-[#333] transition-colors duration-200">
          <h3 className="font-bold text-gray-800 dark:text-gray-300 text-sm mb-2 flex items-center gap-1.5">
            <GitBranch size={16} className="text-orange-500 dark:text-orange-400" />
            파이프라인 설명
          </h3>
          {activeGraphTab === 'AST' && <p><strong className="text-orange-600 dark:text-orange-300">AST (Abstract Syntax Tree):</strong> 사용자의 코드가 구문 분석(Parsing)을 거쳐 의미 단위의 트리로 변환된 모습입니다.</p>}
          {activeGraphTab === 'SSA' && <p className="flex items-center gap-1"><GitMerge size={14} className="text-teal-500 dark:text-teal-400 inline" /> <strong className="text-teal-600 dark:text-teal-300">SSA (Static Single Assignment):</strong> 트리 구조가 실행 가능한 기본 블록(Basic Block)으로 쪼개져 제어 흐름 그래프(CFG)를 형성합니다.</p>}
          {activeGraphTab === 'IR' && <p><strong className="text-purple-600 dark:text-purple-400">IR (Intermediate Representation):</strong> 기계어와 가까운 중간 언어로 변환되어 컴파일러가 최적화를 수행하기 전의 모습입니다.</p>}
          {activeGraphTab === 'ASM' && <p><strong className="text-red-600 dark:text-red-400">ASM (Assembly Code):</strong> 대상 아키텍처(CPU)에 맞게 최종적으로 번역된 어셈블리어 코드 구조입니다.</p>}
          <p className="mt-2 text-[10px] text-gray-500 dark:text-gray-600">※ 이 뷰어는 에디터에 if, for, print/cout 등이 입력될 때 그래프 형태를 실시간으로 간략히 시뮬레이션하여 보여줍니다.</p>
        </div>
      </div>
    </div>
  );
}
