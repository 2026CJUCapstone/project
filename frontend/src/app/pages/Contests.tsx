import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { ArrowRight, CalendarDays, Check, Clock3, Plus, RotateCcw, Search, Trophy, Users } from 'lucide-react';
import { getCurrentUser } from '../services/authApi';
import { contestPageRequest, CONTEST_STATES, type Contest, type ContestState } from '../services/contestApi';
import { ContestEmpty, ContestStatus, contestLength, contestSchedule } from '../components/ContestUI';

const stateOrder: ContestState[] = ['running', 'upcoming', 'finalizing', 'finished', 'draft'];
const filters = [
  { id: 'all', label: '전체' }, { id: 'running', label: '진행 중' },
  { id: 'upcoming', label: '예정' }, { id: 'finished', label: '종료' },
] as const;
type Filter = typeof filters[number]['id'];
const matchesFilter = (contest: Contest, filter: Filter) => filter === 'all' || contest.state === filter || (filter === 'finished' && contest.state === 'finalizing');

function ContestCard({ contest }: { contest: Contest }) {
  return <Link to={`/contests/${contest.id}`} className="contest-card" data-testid="contest-card">
    <div className={`contest-card-cover is-${contest.state}`}>
      <ContestStatus state={contest.state} />
      <Trophy size={76} strokeWidth={1} className="contest-card-emblem" aria-hidden="true" />
      <span className="contest-card-format">개인전 · 고정 배점</span>
    </div>
    <div className="contest-card-body">
      <h3>{contest.title}</h3>
      <div className="contest-card-dates">
        <div><CalendarDays size={14} /><span>시작</span><time dateTime={contest.startsAt}>{contestSchedule(contest.startsAt)}</time></div>
        <div><CalendarDays size={14} /><span>종료</span><time dateTime={contest.endsAt}>{contestSchedule(contest.endsAt)}</time></div>
      </div>
      <div className="contest-card-meta">
        <span><Clock3 size={14} />{contestLength(contest.startsAt, contest.endsAt)}</span>
        <span><Users size={14} />참가자 {contest.participantCount}명</span>
        {contest.joined && <span><Check size={14} />참가 신청 완료</span>}
      </div>
    </div>
    <div className="contest-card-footer"><small>한국 시간 (KST)</small><span>대회 보기 <ArrowRight size={15} /></span></div>
  </Link>;
}

export function Contests() {
  const pageSize = 24;
  const [contests, setContests] = useState<Contest[]>([]);
  const [total, setTotal] = useState(0);
  const [admin, setAdmin] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await contestPageRequest<Contest>('', pageSize, 0, controller.signal,
          { state: filter === 'all' ? undefined : filter, search });
        if (!controller.signal.aborted) { setContests(data.items); setTotal(data.total); setError(''); }
      } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    }, 250);
    if (localStorage.getItem('authToken')) void getCurrentUser().then(u => setAdmin(u.role === 'admin')).catch(() => {});
    return () => { clearTimeout(timer); controller.abort(); };
  }, [filter, refreshKey, search]);
  const loadMore = async () => {
    setLoading(true);
    try {
      const data = await contestPageRequest<Contest>('', pageSize, contests.length, undefined,
        { state: filter === 'all' ? undefined : filter, search });
      setContests(current => [...current, ...data.items.filter(item => !current.some(existing => existing.id === item.id))]); setTotal(data.total); setError('');
    } catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  };
  const visible = contests.filter(c => matchesFilter(c, filter) && c.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <div className="contest-page" data-testid="contest-list-page"><div className="contest-shell">
    <header className="contest-page-heading">
      <div className="contest-heading-main"><div className="contest-heading-icon"><Trophy size={25} /></div><div><h1>콘테스트</h1><p>참가할 대회를 선택하세요.</p></div></div>
      <div className="flex gap-2"><button type="button" className="contest-primary" onClick={() => setRefreshKey(value => value + 1)}><RotateCcw size={17} />새로고침</button>{admin && <Link className="contest-primary" to="/contests/new"><Plus size={17} />대회 만들기</Link>}</div>
    </header>
    <div className="contest-toolbar">
      <nav className="contest-filters" aria-label="대회 상태 필터">{filters.map(item => <button className="contest-filter" key={item.id} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
        {item.label}<span className="contest-filter-count">{contests.filter(c => matchesFilter(c, item.id)).length}</span>
      </button>)}</nav>
      <label className="contest-search"><Search size={16} /><input type="search" aria-label="대회 검색" placeholder="대회 이름 검색" value={search} onChange={e => setSearch(e.target.value)} /></label>
    </div>
    {error && <p role="alert" className="contest-error">{error}</p>}
    {loading ? <ContestEmpty icon={<Clock3 size={24} />} title="대회 목록을 불러오는 중입니다" /> : stateOrder.map(state => {
      const items = visible.filter(c => c.state === state).sort((a, b) => state === 'upcoming' ? Date.parse(a.startsAt) - Date.parse(b.startsAt) : Date.parse(b.startsAt) - Date.parse(a.startsAt));
      return items.length ? <section className="contest-section" key={state}>
        <div className="contest-section-heading"><h2>{CONTEST_STATES[state]}</h2><span>{items.length}개 대회</span></div>
        <div className="contest-grid">{items.map(c => <ContestCard key={c.id} contest={c} />)}</div>
      </section> : null;
    })}
    {!loading && !visible.length && !error && <ContestEmpty icon={<Trophy size={24} />} title={contests.length ? '조건에 맞는 대회가 없습니다' : '아직 등록된 대회가 없습니다'}>{contests.length ? '다른 상태를 선택하거나 검색어를 바꿔보세요.' : '대회가 등록되면 이곳에서 일정과 참가 정보를 확인할 수 있습니다.'}</ContestEmpty>}
    {!loading && contests.length < total && <div className="mt-6 text-center"><button type="button" className="contest-primary" onClick={() => void loadMore()}>대회 더 보기 ({contests.length}/{total})</button></div>}
  </div></div>;
}
