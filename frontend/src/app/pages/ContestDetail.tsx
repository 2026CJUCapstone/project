import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import { ArrowLeft, ArrowRight, BookOpen, CalendarDays, CheckCircle2, ChevronDown, Clock3, FileCode2, Info, LockKeyhole, Trophy, Users } from 'lucide-react';
import { ContestEmpty, ContestStatus, contestLength, contestSchedule } from '../components/ContestUI';
import { useContestTime } from '../services/useContestTime';
import { contestRequest, contestDate, duration, CONTEST_STATES, VERDICTS, type Contest, type ContestSubmission, type Scoreboard } from '../services/contestApi';

export function ContestClock({ contest }: { contest: Contest }) {
  const now = useContestTime(contest.serverTime);
  const target = Date.parse(contest.state === 'upcoming' ? contest.startsAt : contest.endsAt);
  return <span className="contest-clock font-mono">{CONTEST_STATES[contest.state]} {['running', 'upcoming'].includes(contest.state) && `· ${contest.state === 'upcoming' ? '시작까지' : '남은 시간'} ${duration((target - now) / 1000)}`}</span>;
}

export function ContestDetail() {
  const { contestId } = useParams();
  const [contest, setContest] = useState<Contest | null>(null);
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [submissions, setSubmissions] = useState<ContestSubmission[]>([]);
  const [submissionPage, setSubmissionPage] = useState(0);
  const [submissionTotal, setSubmissionTotal] = useState(0);
  const [selectedSubmission, setSelectedSubmission] = useState<ContestSubmission | null>(null);
  const [tab, setTab] = useState<'problems' | 'scoreboard' | 'submissions'>('problems');
  const [error, setError] = useState('');
  const [joining, setJoining] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let busy = false;
    const refresh = async () => {
      if (busy) return;
      busy = true;
      try {
        const data = await contestRequest<Contest>(`/${contestId}`, 'GET', undefined, controller.signal);
        setContest(data);
        setBoard(await contestRequest<Scoreboard>(`/${contestId}/scoreboard`, 'GET', undefined, controller.signal));
        if (localStorage.getItem('authToken')) {
          const mine = await contestRequest<{ submissions: ContestSubmission[]; total: number }>(`/${contestId}/submissions?offset=${submissionPage * 50}&limit=50`, 'GET', undefined, controller.signal);
          setSubmissions(mine.submissions);
          setSubmissionTotal(mine.total);
        }
        setError('');
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
      finally { busy = false; }
    };
    void refresh(); const timer = setInterval(refresh, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [contestId, submissionPage]);
  const viewCode = async (id: string) => {
    try { setSelectedSubmission(await contestRequest<ContestSubmission>(`/${contestId}/submissions/${id}`)); }
    catch (e) { setError((e as Error).message); }
  };
  const join = async () => {
    setJoining(true);
    try { setContest(await contestRequest<Contest>(`/${contestId}/join`, 'POST')); setError(''); }
    catch (e) { setError(localStorage.getItem('authToken') ? (e as Error).message : '상단 로그인 버튼으로 로그인한 후 참가하세요.'); }
    finally { setJoining(false); }
  };
  return <div className="contest-page" data-testid="contest-detail-page"><div className="contest-shell">
    <Link to="/contests" className="contest-back"><ArrowLeft size={15} />콘테스트 목록</Link>
    {error && <p role="alert" className="contest-error">{error}</p>}
    {!contest && !error && <ContestEmpty icon={<Clock3 size={24} />} title="대회를 불러오는 중입니다" />}
    {contest && <>
      <header className="contest-summary">
        <div className="contest-summary-top">
          <div>
            <div className="contest-summary-labels"><ContestStatus state={contest.state} /><span>개인전 · 고정 배점</span></div>
            <h1>{contest.title}</h1>
            <p className="contest-summary-caption"><Clock3 size={14} />진행 시간 {contestLength(contest.startsAt, contest.endsAt)}</p>
          </div>
          <div className="contest-countdown">
            <p className="contest-countdown-label">대회 현황</p><ContestClock contest={contest} />
            <div className="contest-actions">
              {!contest.joined && ['upcoming','running'].includes(contest.state) && <button disabled={joining} onClick={join} className="contest-primary">{joining ? '신청 중…' : '참가 신청'}<ArrowRight size={16} /></button>}
              {contest.joined && <span className="contest-joined"><CheckCircle2 size={16} />참가 신청 완료</span>}
              {contest.canManage && ['draft','upcoming'].includes(contest.state) && <Link to={`/contests/${contest.id}/edit`} className="contest-secondary">대회 관리</Link>}
            </div>
          </div>
        </div>
        <div className="contest-summary-metrics">
          <div className="contest-metric"><p className="contest-metric-label"><CalendarDays size={14} />시작 · KST</p><time className="contest-metric-value" dateTime={contest.startsAt}>{contestSchedule(contest.startsAt)}</time></div>
          <div className="contest-metric"><p className="contest-metric-label"><CalendarDays size={14} />종료 · KST</p><time className="contest-metric-value" dateTime={contest.endsAt}>{contestSchedule(contest.endsAt)}</time></div>
          <div className="contest-metric"><p className="contest-metric-label"><Users size={14} />참가자</p><p className="contest-metric-value">{contest.participantCount}명</p></div>
        </div>
      </header>
      <details className="contest-info">
        <summary><Info size={16} />대회 안내 및 채점 규칙<ChevronDown className="contest-chevron" size={16} /></summary>
        <div className="contest-info-body">
          <div className="prose prose-sm dark:prose-invert max-w-none"><ReactMarkdown>{contest.description}</ReactMarkdown></div>
          <p className="contest-rules">문제별 고정 배점 · 동점: 마지막 득점 시간 + 맞힌 문제의 정답 전 오답당 5분. 컴파일 오류·시스템 오류·미해결 문제의 오답은 패널티에서 제외됩니다.</p>
        </div>
      </details>
      <div className="contest-content">
        <nav className="contest-tabs" aria-label="대회 메뉴">{([
          {id:'problems',label:'문제',icon:BookOpen}, {id:'scoreboard',label:'스코어보드',icon:Trophy}, {id:'submissions',label:'내 제출',icon:FileCode2},
        ] as const).map(({id,label,icon:Icon}) => <button key={id} onClick={() => setTab(id)} className="contest-tab" aria-pressed={tab === id}><Icon size={16} />{label}</button>)}</nav>
        <div className="contest-content-body">
          {tab === 'problems' && <section>
            <div className="contest-content-heading"><h2>대회 문제{contest.problems.length > 0 && ` · ${contest.problems.length}`}</h2><p>모든 테스트를 통과하면 해당 배점을 획득합니다.</p></div>
            {contest.problems.length ? <div className="contest-problem-list">{contest.problems.map(p => <Link className="contest-problem" key={p.id} to={`/contests/${contest.id}/problems/${p.id}`}>
              <span className="contest-problem-letter">{p.label}</span><span className="contest-problem-title">{p.title}</span><span className="contest-problem-score">{p.points}점</span><ArrowRight size={16} />
            </Link>)}</div> : <ContestEmpty icon={<LockKeyhole size={24} />} title={contest.state === 'running' ? '참가 신청 후 문제를 볼 수 있습니다' : contest.state === 'draft' ? '아직 공개되지 않은 대회입니다' : '대회 시작을 기다리고 있습니다'}>
              {contest.state === 'running' ? '위의 참가 신청 버튼을 눌러 대회에 참여하세요. 모든 참가자의 종료 시각은 동일합니다.' : '시작 시각이 되면 참가자에게 문제가 공개됩니다. 스코어보드는 참가 여부와 관계없이 볼 수 있습니다.'}
            </ContestEmpty>}
          </section>}
          {tab === 'scoreboard' && board && <section>
            <div className="contest-content-heading"><h2>{board.state === 'finished' ? '최종 순위' : board.state === 'finalizing' ? '최종 채점 중' : '실시간 순위'}</h2><p>5초마다 갱신 · {board.pendingCount}건 채점 대기</p></div>
            <p className="contest-scroll-hint">좌우로 스크롤하여 문제별 점수를 확인하세요.</p>
            <div className="contest-table-scroll"><table className="contest-table"><thead><tr><th>순위</th><th>참가자</th><th>총점</th><th>패널티</th>{board.problems.map(p => <th key={p.id}>{p.label} ({p.points})</th>)}</tr></thead><tbody>
              {board.rows.map(row => <tr key={row.userId}><td>{row.rank}</td><td>{row.username}</td><td><strong>{row.totalPoints}</strong></td><td className="is-number">{duration(row.penaltySeconds)}</td>{row.problems.map(p => <td key={p.contestProblemId} className={p.points ? 'is-accepted' : p.verdict ? 'is-attempted' : ''}>
                <div>{p.points ? `+${p.points}` : p.verdict ? VERDICTS[p.verdict] || p.verdict : '—'}</div><small>{p.elapsedSeconds !== null && duration(p.elapsedSeconds)}{p.wrongAttempts > 0 && ` (${p.wrongAttempts}회)`}</small>
              </td>)}</tr>)}
            </tbody></table></div>
            {!board.rows.length && <ContestEmpty icon={<Users size={24} />} title="아직 참가자가 없습니다">참가 신청을 하면 이곳에서 순위를 확인할 수 있습니다.</ContestEmpty>}
          </section>}
          {tab === 'submissions' && <section>
            <div className="contest-content-heading"><h2>내 제출 기록</h2><p>본인의 제출 코드만 확인할 수 있습니다.</p></div>
            {submissions.map(s => <div key={s.id} className="contest-submission"><span>{contest.problems.find(p => p.id === s.contestProblemId)?.label} · {s.language}</span><span>{VERDICTS[s.verdict] || s.verdict}</span><time dateTime={s.receivedAt}>{contestDate(s.receivedAt)}</time><button className="contest-code-link" onClick={() => void viewCode(s.id)}>코드 보기</button></div>)}
            {!submissions.length && <ContestEmpty icon={<FileCode2 size={24} />} title="아직 제출한 코드가 없습니다">로그인 후 대회 문제를 풀고 제출하면 채점 결과가 표시됩니다.</ContestEmpty>}
            {submissionTotal > 50 && <div className="contest-pagination"><button disabled={submissionPage === 0} onClick={() => setSubmissionPage(p => p - 1)}>이전</button><span>{submissionPage + 1} / {Math.ceil(submissionTotal / 50)}</span><button disabled={(submissionPage + 1) * 50 >= submissionTotal} onClick={() => setSubmissionPage(p => p + 1)}>다음</button></div>}
            {selectedSubmission && <div className="contest-source"><div><span>내 제출 코드 · {selectedSubmission.language}</span><button onClick={() => setSelectedSubmission(null)}>닫기</button></div><pre>{selectedSubmission.code}</pre></div>}
          </section>}
        </div>
      </div>
    </>}
  </div></div>;
}
