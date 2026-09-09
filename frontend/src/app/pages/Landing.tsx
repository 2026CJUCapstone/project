import {
  ArrowRight,
  Braces,
  CheckCircle2,
  Code2,
  Layers3,
  MessageCircle,
  Play,
  Sparkles,
  Swords,
  Terminal,
  Trophy,
  Zap,
} from 'lucide-react';
import { useNavigate } from 'react-router';

const featureCards = [
  {
    icon: Terminal,
    eyebrow: 'IDE',
    title: '설치 없이 코드 실행',
    description: 'B++, C, C++, Python, Java, JavaScript를 지원합니다. 언어를 선택하고 코드를 실행하면 결과를 확인할 수 있습니다.',
    accent: 'text-blue-600 dark:text-blue-300',
    panel: 'bg-blue-50 dark:bg-blue-500/10',
  },
  {
    icon: Layers3,
    eyebrow: '컴파일 분석',
    title: 'B++ 컴파일 과정 살펴보기',
    description: 'B++ 코드의 AST와 SSA는 그래프로, IR과 어셈블리 코드는 텍스트로 확인할 수 있습니다.',
    accent: 'text-violet-600 dark:text-violet-300',
    panel: 'bg-violet-50 dark:bg-violet-500/10',
  },
  {
    icon: Swords,
    eyebrow: '챌린지',
    title: '알고리즘 문제 풀기',
    description: '난이도와 주제별로 문제를 찾아 풀어보세요. 제출한 코드의 채점 결과와 이전 제출 기록을 확인할 수 있습니다.',
    accent: 'text-emerald-600 dark:text-emerald-300',
    panel: 'bg-emerald-50 dark:bg-emerald-500/10',
  },
  {
    icon: MessageCircle,
    eyebrow: '커뮤니티',
    title: '질문과 풀이 나누기',
    description: '문제를 풀다가 막힌 부분이나 언어 사용법을 질문해 보세요. 자유 게시판에는 서비스 개선 의견도 남길 수 있습니다.',
    accent: 'text-orange-600 dark:text-orange-300',
    panel: 'bg-orange-50 dark:bg-orange-500/10',
  },
];

const steps = [
  ['01', '코드 실행하기', 'IDE에서 언어를 선택하면 기본 예제 코드가 나타납니다. 예제를 그대로 실행하거나 직접 코드를 작성해 보세요.'],
  ['02', 'B++ 컴파일 결과 살펴보기', 'B++ 코드를 실행한 뒤 AST·SSA 그래프와 IR·어셈블리 코드를 살펴보세요. 코드가 분석되고 변환되는 과정을 확인할 수 있습니다.'],
  ['03', '알고리즘 문제 풀기', '챌린지에서 문제를 골라 코드를 제출해 보세요. 채점 결과와 레이팅을 확인하고, 궁금한 점은 커뮤니티에 질문할 수 있습니다.'],
];

export function Landing() {
  const navigate = useNavigate();

  return (
    <div
      data-testid="landing-page"
      className="w-full overflow-y-auto break-keep bg-white text-slate-950 dark:bg-[#0b0d12] dark:text-white"
    >
      <section className="relative isolate overflow-hidden border-b border-slate-200 dark:border-white/10">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(circle_at_18%_14%,rgba(59,130,246,0.14),transparent_32%),radial-gradient(circle_at_82%_76%,rgba(139,92,246,0.12),transparent_28%)] dark:bg-[radial-gradient(circle_at_18%_14%,rgba(59,130,246,0.2),transparent_32%),radial-gradient(circle_at_82%_76%,rgba(139,92,246,0.18),transparent_28%)]" />
        <div className="mx-auto grid min-h-[650px] max-w-7xl items-center gap-14 px-6 py-20 lg:grid-cols-[1.12fr_0.88fr] lg:px-10 lg:py-24">
          <div>
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-bold tracking-[0.18em] text-blue-700 dark:border-blue-400/20 dark:bg-blue-400/10 dark:text-blue-300">
              <Sparkles size={14} /> B++ 온라인 컴파일러
            </div>
            <h1 className="max-w-3xl text-4xl font-black leading-[1.12] tracking-[-0.04em] text-slate-950 sm:text-[42px] lg:text-[38px] xl:text-[46px] dark:text-white">
              브라우저에서 코드를 실행하고
              <br />
              <span className="text-blue-600 dark:text-blue-400">B++의 컴파일 과정을 살펴보세요.</span>
            </h1>
            <p className="mt-7 max-w-2xl text-base leading-8 text-slate-600 sm:text-lg dark:text-slate-300">
              별도 설치 없이 코드를 작성하고 실행할 수 있습니다. B++ 코드의 컴파일 과정을 살펴보거나,
              알고리즘 문제를 풀고 커뮤니티에서 질문을 주고받을 수 있습니다.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => navigate('/ide')}
                className="group inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 text-sm font-bold text-white shadow-lg shadow-blue-600/20 transition hover:bg-blue-700 active:scale-[0.98]"
              >
                <Play size={17} className="fill-current" /> 코드 실행하기
                <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
              </button>
              <button
                type="button"
                onClick={() => navigate('/challenges')}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white/80 px-5 py-3 text-sm font-bold text-slate-800 transition hover:border-slate-400 hover:bg-white dark:border-white/15 dark:bg-white/5 dark:text-slate-100 dark:hover:bg-white/10"
              >
                <Swords size={17} /> 챌린지 둘러보기
              </button>
            </div>
            <div className="mt-8 flex flex-wrap gap-x-6 gap-y-2 text-sm text-slate-500 dark:text-slate-400">
              <span className="inline-flex items-center gap-2"><CheckCircle2 size={15} className="text-emerald-500" /> 회원가입 없이 코드 실행</span>
              <span className="inline-flex items-center gap-2"><CheckCircle2 size={15} className="text-emerald-500" /> 6개 언어 지원</span>
              <span className="inline-flex items-center gap-2"><CheckCircle2 size={15} className="text-emerald-500" /> B++ 컴파일 과정 분석</span>
            </div>
          </div>

          <div className="relative mx-auto w-full max-w-2xl" aria-label="B++ 컴파일러 미리보기">
            <div className="absolute -inset-5 -z-10 rounded-[2rem] bg-gradient-to-br from-blue-500/15 to-violet-500/15 blur-2xl" />
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-[#0c1018] shadow-2xl shadow-slate-900/20 dark:border-white/10">
              <div className="flex h-11 items-center justify-between border-b border-white/10 bg-[#121722] px-4">
                <div className="flex gap-1.5" aria-hidden="true">
                  <span className="h-2.5 w-2.5 rounded-full bg-red-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                </div>
                <span className="font-mono text-[11px] tracking-wide text-slate-500">main.bpp</span>
                <span className="rounded bg-blue-500/15 px-2 py-1 font-mono text-[10px] text-blue-300">B++</span>
              </div>
              <div className="grid min-h-[370px] grid-cols-1 md:grid-cols-[1.2fr_0.8fr]">
                <div className="border-b border-white/10 p-5 font-mono text-[13px] leading-7 md:border-b-0 md:border-r">
                  <div><span className="select-none pr-4 text-slate-700">1</span><span className="text-violet-300">import</span> <span className="text-sky-300">emitln</span> <span className="text-violet-300">from</span> <span className="text-slate-300">std.io;</span></div>
                  <div><span className="select-none pr-4 text-slate-700">2</span></div>
                  <div><span className="select-none pr-4 text-slate-700">3</span><span className="text-violet-300">func</span> <span className="text-sky-300">main</span><span className="text-slate-300">() -&gt; </span><span className="text-emerald-300">u64</span> <span className="text-slate-300">{'{'}</span></div>
                  <div><span className="select-none pr-4 text-slate-700">4</span><span className="pl-4 text-sky-300">emitln</span><span className="text-slate-300">(</span><span className="text-amber-300">&quot;Hello, B++!&quot;</span><span className="text-slate-300">);</span></div>
                  <div><span className="select-none pr-4 text-slate-700">5</span><span className="pl-4 text-violet-300">return</span> <span className="text-orange-300">0</span><span className="text-slate-300">;</span></div>
                  <div><span className="select-none pr-4 text-slate-700">6</span><span className="text-slate-300">{'}'}</span></div>
                  <div className="mt-10 rounded-lg border border-emerald-400/20 bg-emerald-400/5 p-3 text-xs leading-6 text-emerald-300">
                    <span className="text-slate-500">$</span> bpp run main.bpp<br />
                    Hello, B++!<br />
                    <span className="text-slate-500">Process exited with code 0</span>
                  </div>
                </div>
                <div className="flex flex-col justify-center gap-3 bg-[#0a0d14] p-5">
                  {['Source', 'AST', 'SSA', 'ASM'].map((label, index) => (
                    <div key={label} className="relative">
                      <div className={`flex items-center justify-between rounded-lg border px-3 py-2.5 ${index === 2 ? 'border-blue-400/40 bg-blue-400/10 text-blue-200' : 'border-white/10 bg-white/[0.03] text-slate-300'}`}>
                        <span className="flex items-center gap-2 text-xs font-semibold"><Braces size={14} /> {label}</span>
                        <span className="font-mono text-[10px] text-slate-600">0{index + 1}</span>
                      </div>
                      {index < 3 && <div className="mx-auto h-3 w-px bg-white/15" />}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section aria-labelledby="bpp-language-heading" className="border-b border-slate-200 bg-white py-12 dark:border-white/10 dark:bg-[#0b0d12] sm:py-16">
        <div className="mx-auto grid max-w-7xl gap-6 px-6 lg:grid-cols-[0.8fr_1.2fr] lg:gap-12 lg:px-10">
          <div>
            <div aria-hidden="true" className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-400/10 dark:text-blue-400">
              <Braces size={22} />
            </div>
            <h2 id="bpp-language-heading" className="text-2xl font-bold tracking-tight sm:text-3xl">B++는 어떤 언어인가요?</h2>
          </div>
          <div className="max-w-2xl space-y-3 break-keep text-base leading-8 text-slate-600 dark:text-slate-300">
            <p>B++는 컴파일러의 동작 원리를 배우고 알고리즘 문제를 풀기 위해 만든 프로그래밍 언어입니다.</p>
            <p>직접 작성한 코드가 어떻게 분석되고 실행 파일로 바뀌는지 단계별로 살펴볼 수 있습니다.</p>
          </div>
        </div>
      </section>

      <section className="border-b border-slate-200 bg-slate-50 py-20 dark:border-white/10 dark:bg-[#0e1118]">
        <div className="mx-auto max-w-7xl px-6 lg:px-10">
          <div className="max-w-2xl">
            <p className="text-xs font-bold tracking-[0.2em] text-blue-600 dark:text-blue-400">주요 기능</p>
            <h2 className="mt-3 text-3xl font-black tracking-[-0.03em] sm:text-4xl">코드 실행과 문제 풀이</h2>
            <p className="mt-4 leading-7 text-slate-600 dark:text-slate-400">코드 실행은 IDE에서, 알고리즘 연습은 챌린지에서 시작하세요. 질문이나 풀이 이야기는 커뮤니티에 남길 수 있습니다.</p>
          </div>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {featureCards.map(({ icon: Icon, eyebrow, title, description, accent, panel }) => (
              <article key={title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg dark:border-white/10 dark:bg-white/[0.035]">
                <div className={`mb-5 flex h-11 w-11 items-center justify-center rounded-xl ${panel} ${accent}`}><Icon size={21} /></div>
                <p className={`text-[10px] font-extrabold tracking-[0.18em] ${accent}`}>{eyebrow}</p>
                <h3 className="mt-2 text-lg font-bold text-slate-900 dark:text-white">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600 dark:text-slate-400">{description}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-white py-20 dark:bg-[#0b0d12]">
        <div className="mx-auto grid max-w-7xl gap-12 px-6 lg:grid-cols-[0.72fr_1.28fr] lg:px-10">
          <div>
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-900 text-white dark:bg-white dark:text-slate-950"><Zap size={22} /></div>
            <h2 className="mt-6 text-3xl font-black tracking-[-0.03em]">예제 코드부터 실행해 보세요</h2>
            <p className="mt-4 max-w-md leading-7 text-slate-600 dark:text-slate-400">B++ 문법이 낯설다면 기본 예제부터 실행해 보세요. 코드를 조금씩 바꾸고 결과가 어떻게 달라지는지 확인하면 됩니다.</p>
            <button type="button" onClick={() => navigate('/community')} className="mt-6 inline-flex items-center gap-2 text-sm font-bold text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">
              커뮤니티 가기 <ArrowRight size={16} />
            </button>
          </div>
          <ol className="grid gap-4">
            {steps.map(([number, title, description]) => (
              <li key={number} className="grid grid-cols-[58px_1fr] gap-4 rounded-2xl border border-slate-200 p-5 dark:border-white/10 dark:bg-white/[0.025]">
                <span className="font-mono text-sm font-black text-blue-600 dark:text-blue-400">{number}</span>
                <div><h3 className="font-bold text-slate-900 dark:text-white">{title}</h3><p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-400">{description}</p></div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="border-t border-slate-200 bg-slate-950 px-6 py-16 text-white dark:border-white/10">
        <div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-8 lg:flex-row lg:items-center">
          <div><h2 className="text-3xl font-black tracking-tight">코드를 실행해 보세요</h2><p className="mt-3 text-slate-400">IDE에서 언어를 선택하고 시작하면 됩니다.</p></div>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={() => navigate('/ide')} className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-3 text-sm font-bold text-slate-950 hover:bg-slate-100"><Code2 size={17} /> IDE 열기</button>
            <button type="button" onClick={() => navigate('/leaderboard')} className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-5 py-3 text-sm font-bold text-white hover:bg-white/10"><Trophy size={17} /> 리더보드 보기</button>
          </div>
        </div>
      </section>
    </div>
  );
}
