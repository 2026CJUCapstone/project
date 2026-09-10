import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
import { Admin } from './Admin';

describe('Admin access gate', () => {
  beforeEach(() => localStorage.clear());

  it('shows a login requirement instead of management fields to a signed-out visitor', async () => {
    render(<MemoryRouter><Admin /></MemoryRouter>);

    expect(await screen.findByRole('heading', { name: '관리자 로그인이 필요합니다' })).toBeInTheDocument();
    expect(screen.getByText('문제 생성과 수정은 관리자 계정으로 로그인한 뒤 사용할 수 있습니다.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '홈에서 로그인하기' })).toHaveAttribute('href', '/');
    expect(screen.queryByPlaceholderText('아이디')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '문제 추가' })).not.toBeInTheDocument();
  });
});
