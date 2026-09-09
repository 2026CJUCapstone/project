import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { contestRequest, type ContestProblemDetail } from '../services/contestApi';
import { ContestClock } from './ContestDetail';
import { IDE } from './IDE';

export function ContestProblemPage() {
  const { contestId, contestProblemId } = useParams();
  const [problem, setProblem] = useState<ContestProblemDetail | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setProblem(null); setError('');
    const refresh = () => contestRequest<ContestProblemDetail>(`/${contestId}/problems/${contestProblemId}`, 'GET', undefined, controller.signal).then(setProblem).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    void refresh(); const timer=setInterval(refresh,5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [contestId, contestProblemId]);
  return <div className="flex h-full min-h-0 w-full flex-col bg-slate-900 text-slate-100">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-700 px-4 py-2 text-sm"><Link to={`/contests/${contestId}`} className="text-blue-400">← 대회로 돌아가기</Link>{problem && <ContestClock contest={problem.contest} />}</div>
    {error && <p role="alert" className="p-4 text-red-400">{error}</p>}
    {problem && <div className="min-h-0 flex-1"><IDE key={`${contestId}:${contestProblemId}`} contestProblem={problem} /></div>}
  </div>;
}
