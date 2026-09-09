import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { useCompilerStore } from '../store/compilerStore';
import { useContestTime } from '../services/useContestTime';
import { contestRequest, VERDICTS, type Contest, type ContestSubmission } from '../services/contestApi';

export function ContestJudgePanel({ contest, problemId }: { contest: Contest; problemId: string }) {
  const { code, language } = useCompilerStore();
  const [submission, setSubmission] = useState<ContestSubmission | null>(null);
  const pendingRequest = useRef<{code:string; language:string; requestId:string} | null>(null);
  const [error, setError] = useState(''); const [sending, setSending] = useState(false);
  const now = useContestTime(contest.serverTime);
  useEffect(() => {
    if (!submission || submission.status === 'completed') return;
    const controller = new AbortController(); let busy = false;
    const timer = setInterval(async () => {
      if (busy) return; busy = true;
      try { setSubmission(await contestRequest<ContestSubmission>(`/${contest.id}/submissions/${submission.id}`, 'GET', undefined, controller.signal)); }
      catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
      finally { busy = false; }
    }, 1000);
    return () => { clearInterval(timer); controller.abort(); };
  }, [contest.id, submission?.id, submission?.status]);
  const submit = async () => {
    setSending(true); setError('');
    if (!pendingRequest.current || pendingRequest.current.code !== code || pendingRequest.current.language !== language) {
      pendingRequest.current = {code, language, requestId: crypto.randomUUID()};
    }
    try {
      setSubmission(await contestRequest<ContestSubmission>(`/${contest.id}/problems/${problemId}/submit`, 'POST', pendingRequest.current));
      pendingRequest.current = null;
    }
    catch (e) { setError((e as Error).message); }
    finally { setSending(false); }
  };
  const closed = now >= Date.parse(contest.endsAt) || now < Date.parse(contest.startsAt);
  return <div className="space-y-3 p-4">
    <button onClick={submit} disabled={closed || !contest.joined || sending || !code.trim()} className="rounded bg-green-600 px-4 py-2 text-white disabled:bg-slate-700 disabled:text-slate-400">{sending ? '접수 중…' : closed ? '제출 기간이 아닙니다' : '대회 제출'}</button>
    {!contest.joined && <p className="text-sm text-amber-400">대회 상세에서 참가 신청 후 제출하세요.</p>}
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
    {submission && <p data-testid="contest-verdict" className={submission.verdict==='accepted'?'text-green-400':'text-amber-400'}>{VERDICTS[submission.verdict] || submission.verdict}</p>}
    <Link className="block text-sm text-blue-400" to={`/contests/${contest.id}`}>대회 문제·내 제출·스코어보드</Link>
  </div>;
}
