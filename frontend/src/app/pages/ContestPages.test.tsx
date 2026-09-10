import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Contests } from './Contests';
import { ContestDetail } from './ContestDetail';
import { contestPageRequest, contestRequest, type Contest } from '../services/contestApi';

vi.mock('../services/contestApi', async importOriginal => ({
  ...await importOriginal<typeof import('../services/contestApi')>(), contestRequest: vi.fn(), contestPageRequest: vi.fn(),
}));
const contest: Contest = {id:'c',title:'테스트 대회',description:'규칙',published:true,
  startsAt:'2030-01-01T00:00:00Z',endsAt:'2030-01-01T02:00:00Z',serverTime:'2030-01-01T01:00:00Z',
  state:'running',joined:false,canManage:false,participantCount:2,
  problems:[{id:'cp',problemId:'p',label:'A',title:'문제 A',points:500,difficulty:'iron5'}]};

describe('contest pages', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });
  it('groups public contests and links to the detail page', async () => {
    vi.mocked(contestPageRequest).mockResolvedValue({ items: [contest], total: 1 });
    render(<MemoryRouter><Contests /></MemoryRouter>);
    expect(await screen.findByRole('heading',{name:'진행 중'})).toBeInTheDocument();
    expect(screen.getByRole('link',{name:/테스트 대회/})).toHaveAttribute('href','/contests/c');
    expect(screen.queryByRole('link',{name:'대회 만들기'})).not.toBeInTheDocument();
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
