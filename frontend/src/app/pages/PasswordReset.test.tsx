import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { requestPasswordReset } from '../services/authApi';
import { PasswordReset } from './PasswordReset';

vi.mock('../components/AuthModal', () => ({ AuthModal: () => <div data-testid="reset-modal" /> }));
vi.mock('../services/authApi', () => ({ requestPasswordReset: vi.fn() }));

describe('PasswordReset', () => {
  beforeEach(() => vi.clearAllMocks());

  it('opens an explicit forgot-password request form when no reset token is present', () => {
    render(<MemoryRouter initialEntries={['/reset-password']}><PasswordReset /></MemoryRouter>);

    expect(screen.getByRole('heading', { name: '비밀번호 찾기' })).toBeInTheDocument();
    expect(screen.getByLabelText('아이디 또는 이메일')).toBeInTheDocument();
    expect(screen.queryByText('비밀번호 재설정을 준비 중입니다.')).not.toBeInTheDocument();
    expect(screen.queryByTestId('reset-modal')).not.toBeInTheDocument();
  });

  it('requests a reset using the identity entered on the route', async () => {
    vi.mocked(requestPasswordReset).mockResolvedValue({ message: '재설정 안내를 보냈습니다.' });
    render(<MemoryRouter initialEntries={['/reset-password']}><PasswordReset /></MemoryRouter>);

    fireEvent.change(screen.getByLabelText('아이디 또는 이메일'), { target: { value: 'coder@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: '재설정 안내 받기' }));

    expect(await screen.findByRole('status')).toHaveTextContent('재설정 안내를 보냈습니다.');
    expect(requestPasswordReset).toHaveBeenCalledWith('coder@example.com');
  });
});
