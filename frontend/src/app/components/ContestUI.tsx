import { type ReactNode } from 'react';
import { CONTEST_STATES, type ContestState } from '../services/contestApi';
import './contests.css';

export function ContestStatus({ state }: { state: ContestState }) {
  return <span className={`contest-status is-${state}`}><span aria-hidden="true" />{CONTEST_STATES[state]}</span>;
}

export function ContestEmpty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return <div className="contest-empty"><div className="contest-empty-icon">{icon}</div><h3>{title}</h3>{children && <p>{children}</p>}</div>;
}

export function contestSchedule(date: string) {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).format(new Date(date));
}

export function contestLength(start: string, end: string) {
  const minutes = Math.max(0, Math.round((Date.parse(end) - Date.parse(start)) / 60000));
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours}시간${minutes % 60 ? ` ${minutes % 60}분` : ''}` : `${minutes}분`;
}
