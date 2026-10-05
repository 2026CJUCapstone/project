import { useEffect, useState, useSyncExternalStore } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ArrowLeft, CircleHelp } from 'lucide-react';
import { getAuthScope, subscribeAuthIdentity } from '../services/authIdentity';
import { getProblem } from '../services/problemApi';
import { contestRequest, type ContestProblemDetail } from '../services/contestApi';
import { JUDGE_POLICY_LANGUAGES, type PublicJudgeLimits } from '../services/judgePolicyTypes';
import { JudgeLimitTable } from '../components/JudgeLimitTable';

const labels = { bpp: 'B++', c: 'C', cpp: 'C++', python: 'Python', java: 'Java', javascript: 'JavaScript' };
interface HelpProblem {
  title: string;
  judgeLimits?: PublicJudgeLimits | null;
  judgePolicyLegacy?: boolean;
  judgePolicyCompatibility?: boolean;
}

export function JudgingHelp() {
  const scope = useSyncExternalStore(subscribeAuthIdentity, getAuthScope, () => 'guest');
  const [query] = useSearchParams();
  const problemId = query.get('problem');
  const contestId = query.get('contest');
  const language = query.get('language') || 'bpp';
  const validId = (value: string | null) => value === null || (value.trim() === value && value.length > 0 && value.length <= 128);
  const invalid = !validId(problemId) || !validId(contestId) || Boolean(contestId && !problemId)
    || query.getAll('problem').length > 1 || query.getAll('contest').length > 1;
  // No statement, policy or title from the former account/route survives a switch.
  return <HelpContent key={`${scope}:${contestId}:${problemId}:${invalid}`} scope={scope}
    problemId={problemId} contestId={contestId} initialLanguage={language} invalid={invalid} />;
}

function HelpContent({ scope, problemId, contestId, initialLanguage, invalid }: {
  scope: string; problemId: string | null; contestId: string | null; initialLanguage: string; invalid: boolean;
}) {
  const [problem, setProblem] = useState<HelpProblem | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [language, setLanguage] = useState(initialLanguage);
  useEffect(() => { setLanguage(initialLanguage); }, [initialLanguage]);
  useEffect(() => {
    if (!problemId || invalid) return;
    const controller = new AbortController();
    let active = true;
    setProblem(null); setError('');
    const request = contestId
      ? contestRequest<ContestProblemDetail>(`/${encodeURIComponent(contestId)}/problems/${encodeURIComponent(problemId)}`, 'GET', undefined, controller.signal)
      : getProblem(problemId, controller.signal);
    void request.then(value => {
      if (active && !controller.signal.aborted && getAuthScope() === scope) {
        // Retain only public presentation fields, never admin raw policies/tests.
        setProblem({ title: value.title, judgeLimits: value.judgeLimits,
          judgePolicyLegacy: value.judgePolicyLegacy, judgePolicyCompatibility: value.judgePolicyCompatibility });
      }
    }).catch(() => {
      if (active && !controller.signal.aborted && getAuthScope() === scope)
        setError('문제의 채점 제한을 불러올 수 없습니다. 로그인·참가 여부와 대회 공개 시간을 확인하세요.');
    });
    return () => { active = false; controller.abort(); };
  }, [scope, problemId, contestId, invalid, retry]);
  const backTo = problemId && !invalid
    ? contestId ? `/contests/${encodeURIComponent(contestId)}/problems/${encodeURIComponent(problemId)}` : `/problems/${encodeURIComponent(problemId)}`
    : '/problems';

  return <div className="h-full min-h-0 w-full overflow-y-auto bg-gray-50 text-gray-900 dark:bg-[#0d0d0d] dark:text-gray-100">
    <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6 sm:py-10">
      <Link to={backTo} className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-blue-600 dark:text-gray-400 dark:hover:text-blue-400"><ArrowLeft size={16} />{problemId && !invalid ? '문제로 돌아가기' : '문제 목록으로'}</Link>
      <header><h1 className="flex items-center gap-2 text-2xl font-bold"><CircleHelp size={24} />도움말·FAQ</h1><p className="mt-2 text-sm text-gray-500 dark:text-gray-400">코드 제출과 채점 제한에 관한 안내입니다.</p></header>
      {(problemId || invalid) && <section aria-labelledby="problem-help-heading" className="space-y-3">
        <h2 id="problem-help-heading" className="text-lg font-semibold">이 문제의 채점 제한</h2>
        {invalid ? <p role="alert" className="text-sm text-red-600 dark:text-red-400">문제 링크가 올바르지 않습니다. 문제 화면에서 도움말을 다시 열어주세요.</p>
          : error ? <div role="alert" className="space-y-2 text-sm text-red-600 dark:text-red-400"><p>{error}</p><button onClick={() => setRetry(value => value + 1)} className="rounded border border-gray-300 px-3 py-1 text-gray-800 dark:border-[#444] dark:text-gray-100">다시 시도</button></div>
            : !problem ? <p role="status" className="text-sm text-gray-500 dark:text-gray-400">채점 제한을 불러오는 중...</p>
              : <><p className="break-words text-sm font-medium">{problem.title}</p><label className="flex items-center gap-3 text-sm">언어<select value={language} onChange={event => setLanguage(event.target.value)} className="rounded border border-gray-300 bg-white px-3 py-1.5 dark:border-[#444] dark:bg-[#1e1e1e]">
                {!JUDGE_POLICY_LANGUAGES.includes(language as typeof JUDGE_POLICY_LANGUAGES[number]) && <option value={language}>{language}</option>}
                {JUDGE_POLICY_LANGUAGES.map(value => <option key={value} value={value}>{labels[value]}</option>)}
              </select></label><JudgeLimitTable detailed policy={problem.judgeLimits ?? null} selectedLanguage={language}
                legacy={problem.judgePolicyLegacy} compatibility={problem.judgePolicyCompatibility} /></>}
      </section>}
      <section aria-label="채점 FAQ" className="divide-y divide-gray-200 overflow-hidden rounded-xl border border-gray-200 bg-white dark:divide-[#333] dark:border-[#333] dark:bg-[#111]">
        {[
          ['채점은 어떻게 진행되나요?', '제출한 코드를 선택한 언어로 준비한 뒤, 문제의 테스트를 실행해 결과를 비교합니다. 예제뿐 아니라 공개되지 않은 테스트도 통과해야 정답입니다. 컴파일과 실행에는 각각 별도의 자원 제한이 적용됩니다.'],
          ['시간 제한은 어떻게 계산하나요?', 'CPU 시간은 코드가 CPU를 사용한 시간이고, Wall 시간은 실행을 시작해서 끝날 때까지 실제로 흐른 시간입니다. 둘 중 하나라도 제한을 넘으면 시간 초과가 될 수 있습니다. 문제 화면에는 선택한 언어의 두 제한을 함께 표시합니다.'],
          ['언어마다 제한이 다른 이유는 무엇인가요?', '컴파일 방식과 실행 환경에 따라 같은 알고리즘도 걸리는 시간과 필요한 메모리가 다릅니다. 제한은 문제와 언어별로 정해지며, 모든 문제에 공통 배수를 적용하는 것은 아닙니다. 정확한 수치는 문제 화면의 채점 도움말에서 확인하세요. 대회 문제는 대회용으로 고정된 제한을 사용합니다.'],
          ['메모리·출력·프로세스 제한은 무엇인가요?', '메모리는 실행 환경 전체가 사용할 수 있는 용량입니다. 출력 제한은 출력할 수 있는 데이터의 양, PID 제한은 동시에 사용할 수 있는 프로세스·스레드 수, 임시 저장소 제한은 작업 중 저장할 수 있는 파일 용량입니다. 상세 수치는 이 문제의 실행·컴파일 제한에 따로 표시됩니다. MiB와 GiB는 각각 1024를 기준으로 한 메모리 단위입니다.'],
          ['기존 문제 호환 정책은 무엇인가요?', '기존 문제 중에는 새로 측정한 정책 대신 이전 실행 환경에 맞춘 고정 제한을 사용하는 문제가 있습니다. 도움말에서 호환 정책 여부를 확인할 수 있으며, 표시된 언어별 제한은 실제 채점에도 적용됩니다. 확정된 제한이 없으면 임의의 기본값을 표시하지 않습니다.'],
          ['채점 결과가 오류로 나왔어요.', '시간·메모리·출력·프로세스 제한 초과는 해당 자원 제한을 넘었다는 뜻입니다. 컴파일 오류는 실행 전에 코드를 준비하지 못한 경우이고, 런타임 오류는 실행 중 정상적으로 끝나지 못한 경우입니다. 시스템 오류는 채점 환경의 문제일 수 있으므로 제출 기록을 확인한 뒤 관리자에게 알려주세요.'],
        ].map(([question, answer]) => <details key={question} className="px-4 py-4 sm:px-5"><summary className="cursor-pointer text-sm font-semibold focus-visible:outline-2 focus-visible:outline-blue-500">{question}</summary><p className="mt-3 text-sm leading-7 text-gray-600 dark:text-gray-300">{answer}</p></details>)}
      </section>
    </div>
  </div>;
}
