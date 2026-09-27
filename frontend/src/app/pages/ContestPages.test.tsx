import { act, fireEvent, render, screen } from '@testing-library/react';
import { setAuthToken } from '../services/authIdentity';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Contests } from './Contests';
import { ContestDetail } from './ContestDetail';
import { contestPageRequest, contestRequest, VERDICTS, type Contest } from '../services/contestApi';

vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(), contestRequest: vi.fn(), contestPageRequest: vi.fn(),
}));
const contest: Contest = {id:'c',title:'테스트 대회',description:'규칙',published:true,
  startsAt:'2030-01-01T00:00:00Z',endsAt:'2030-01-01T02:00:00Z',serverTime:'2030-01-01T01:00:00Z',
  state:'running',joined:false,canManage:false,participantCount:2,
  problems:[{id:'cp',problemId:'p',label:'A',title:'문제 A',points:500,difficulty:'iron5'}]};

describe('contest pages', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });
  it('clears the old account immediately while the new account response is pending', async () => {
    setAuthToken('first-private-account');
    vi.mocked(contestRequest).mockImplementation(async path => {
      if (path?.endsWith('/scoreboard')) return { rows: [], problems: [], pendingCount: 0, state: 'running' } as never;
      if (path?.includes('/submissions')) return { submissions: [], total: 0 } as never;
      return { ...contest, title: '첫 계정 비공개 대회 제목' } as never;
    });
    render(<MemoryRouter initialEntries={['/contests/c']}><Routes><Route path='/contests/:contestId' element={<ContestDetail />} /></Routes></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: '첫 계정 비공개 대회 제목' })).toBeInTheDocument();
    vi.mocked(contestRequest).mockImplementation(() => new Promise(() => {}));
    act(() => setAuthToken('second-private-account'));
    expect(screen.queryByText('첫 계정 비공개 대회 제목')).not.toBeInTheDocument();
    expect(screen.getByText('대회를 불러오는 중입니다')).toBeInTheDocument();
  });
  it('groups public contests and links to the detail page', async () => {
    vi.mocked(contestPageRequest).mockResolvedValue({ items: [contest], total: 1 });
    render(<MemoryRouter><Contests /></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:'진행 중'})).toBeInTheDocument();
    expect(screen.getByRole('link',{name:/테스트 대회/})).toHaveAttribute('href','/contests/c');
    expect(screen.queryByRole('link',{name:'대회 만들기'})).not.toBeInTheDocument();
  });
  it('shows UTC contest timestamps in KST across a date boundary', async () => {
    const startsAt = '2029-12-31T15:00:00Z';
    const endsAt = '2029-12-31T16:30:00Z';
    vi.mocked(contestRequest).mockImplementation(async path => path?.endsWith('/scoreboard')
      ? { rows: [], problems: [], pendingCount: 0, state: 'upcoming' } as never
      : { ...contest, startsAt, endsAt, state: 'upcoming' } as never);
    render(<MemoryRouter initialEntries={['/contests/c']}><Routes><Route path='/contests/:contestId' element={<ContestDetail />} /></Routes></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '테스트 대회' })).toBeInTheDocument();
    const start = screen.getByText('시작 · KST').closest('.contest-metric')?.querySelector('time');
    const end = screen.getByText('종료 · KST').closest('.contest-metric')?.querySelector('time');
    expect(start).toHaveAttribute('dateTime', startsAt);
    expect(start).toHaveTextContent(/2030.*01.*01.*00:00/);
    expect(end).toHaveAttribute('dateTime', endsAt);
    expect(end).toHaveTextContent(/2030.*01.*01.*01:30/);
  });
  it('labels runtime output and process limits separately from compiler resource failures', () => {
    expect(VERDICTS.output_limit_exceeded).toBe('출력 초과');
    expect(VERDICTS.process_limit_exceeded).toBe('프로세스 제한 초과');
    expect(VERDICTS.compile_resource_error).toBe('컴파일 자원 초과');
  });
  it('uses server time, joins, and shows shared ranks without source code', async () => {
    const rows = ['alice','bob'].map(userId => ({userId,username:userId,rank:1,totalPoints:500,penaltySeconds:900,
      problems:[{contestProblemId:'cp',points:500,wrongAttempts:1,elapsedSeconds:600,pending:false,verdict:'accepted'}]}));
    vi.mocked(contestRequest).mockImplementation(async path => {
      if (path?.endsWith('/scoreboard')) return {rows,problems:[{id:'cp',label:'A',points:500}],pendingCount:0,state:'running'} as never;
      return {...contest,joined:path?.endsWith('/join')} as never;
    });
    render(<MemoryRouter initialEntries={['/contests/c']}><Routes><Route path='/contests/:contestId' element={<ContestDetail />} /></Routes></MemoryRouter>);
    expect(await screen.findByText(/남은 시간 01:00:00/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'참가 신청'}));
    expect(await screen.findByText('참가 신청 완료')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'스코어보드'}));
    expect(await screen.findAllByRole('cell',{name:'1'})).toHaveLength(2);
    expect(screen.getAllByText('00:15:00')).toHaveLength(2);
    expect(screen.queryByText('코드 보기')).not.toBeInTheDocument();
  });

  it('shows public ranking-correction notes after an ended contest', async () => {
    const corrections = { total: 1, items: [{ revision: 2, appliedAt: '2030-01-01T02:30:00Z', note: '테스트 케이스 오류를 정정했습니다.' }] };
    vi.mocked(contestRequest).mockImplementation(async path => path?.endsWith('/scoreboard')
      ? { rows: [], problems: [], pendingCount: 0, state: 'finished', corrections } as never
      : { ...contest, state: 'finished', corrections } as never);

    render(<MemoryRouter initialEntries={['/contests/c']}><Routes><Route path='/contests/:contestId' element={<ContestDetail />} /></Routes></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '순위 정정 안내' })).toBeInTheDocument();
    expect(screen.getByText('재채점 결과에 따른 순위 정정 1건이 최종 순위에 반영되었습니다.')).toBeInTheDocument();
    expect(screen.getByText('테스트 케이스 오류를 정정했습니다.')).toBeInTheDocument();
    expect(screen.getByText('개정 2')).toBeInTheDocument();
  });

  it('does not invent a correction notice when an ended contest omits the optional data', async () => {
    vi.mocked(contestRequest).mockImplementation(async path => path?.endsWith('/scoreboard')
      ? { rows: [], problems: [], pendingCount: 0, state: 'finished' } as never
      : { ...contest, state: 'finished' } as never);

    render(<MemoryRouter initialEntries={['/contests/c']}><Routes><Route path='/contests/:contestId' element={<ContestDetail />} /></Routes></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '테스트 대회' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: '순위 정정 안내' })).not.toBeInTheDocument();
  });

  it('renders multiple contest cards, filters and searches without changing the selected contest', async () => {
    vi.mocked(contestPageRequest).mockResolvedValue({ items: [
      contest, {...contest,id:'next',title:'다음 대회',state:'upcoming'}, {...contest,id:'past',title:'지난 대회',state:'finished'},
    ], total: 3 });
    render(<MemoryRouter><Contests /></MemoryRouter>);
    expect(await screen.findAllByTestId('contest-card')).toHaveLength(3);
    fireEvent.click(screen.getByRole('button',{name:/^예정/}));
    expect(screen.getAllByTestId('contest-card')).toHaveLength(1);
    expect(screen.getByRole('link',{name:/다음 대회/})).toHaveAttribute('href','/contests/next');
    fireEvent.click(screen.getByRole('button',{name:/^전체/}));
    fireEvent.change(screen.getByRole('searchbox',{name:'대회 검색'}),{target:{value:'지난'}});
    expect(screen.getAllByTestId('contest-card')).toHaveLength(1);
    expect(screen.getByRole('link',{name:/지난 대회/})).toHaveAttribute('href','/contests/past');
    fireEvent.change(screen.getByRole('searchbox'),{target:{value:'없음'}});
    expect(screen.getByText('조건에 맞는 대회가 없습니다')).toBeInTheDocument();
  });

  it('explains missing registration separately from the pre-start state', async () => {
    vi.mocked(contestRequest).mockImplementation(async path => path?.endsWith('/scoreboard')
      ? {rows:[],problems:[],pendingCount:0,state:'running'} as never : {...contest,problems:[]} as never);
    render(<MemoryRouter initialEntries={['/contests/c']}><Routes><Route path='/contests/:contestId' element={<ContestDetail />} /></Routes></MemoryRouter>);
    expect(await screen.findByText('참가 신청 후 문제를 볼 수 있습니다')).toBeInTheDocument();
    expect(screen.getByRole('link',{name:'콘테스트 목록'})).toHaveAttribute('href','/contests');
    expect(screen.getByText('대회 안내 및 채점 규칙').closest('details')).not.toHaveAttribute('open');
  });
});
