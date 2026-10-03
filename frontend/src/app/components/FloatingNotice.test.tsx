import { cleanup, fireEvent, render, screen, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FloatingNotice } from './FloatingNotice';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('FloatingNotice', () => {
  it('renders the alert through a portal outside the component render container', () => {
    const onDismiss = vi.fn();
    const { container } = render(<FloatingNotice message="불러오지 못했습니다." onDismiss={onDismiss} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('불러오지 못했습니다.');
    expect(document.body).toContainElement(alert);
    expect(container).not.toContainElement(alert);
    expect(alert.closest('[data-testid="floating-notice-layer"]')?.parentElement).toBe(document.body);
  });

  it('keeps the message as plain text and does not interpret HTML', () => {
    const message = '<img src=x onerror=alert(1)> <strong>위험한 입력</strong>';

    render(<FloatingNotice message={message} onDismiss={vi.fn()} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(message);
    expect(alert.querySelector('img')).toBeNull();
    expect(alert.querySelector('strong')).toBeNull();
  });

  it('calls onDismiss when the 알림 닫기 button is pressed', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="닫을 수 있는 알림" onDismiss={onDismiss} />);

    fireEvent.click(screen.getByRole('button', { name: '알림 닫기' }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('automatically dismisses after six seconds by default', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="잠시 표시되는 알림" onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('stays visible when duration is zero', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="해결될 때까지 표시" onDismiss={onDismiss} duration={0} />);

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(onDismiss).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('cleans up the dismissal timer when unmounted', () => {
    const onDismiss = vi.fn();
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout');
    const { unmount } = render(<FloatingNotice message="사라지는 알림" onDismiss={onDismiss} />);

    unmount();
    act(() => {
      vi.advanceTimersByTime(6000);
    });

    expect(clearTimeoutSpy).toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('pauses dismissal while hovered and resumes after the pointer leaves', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="마우스를 올려 둔 알림" onDismiss={onDismiss} />);
    const alert = screen.getByRole('alert');

    fireEvent.mouseEnter(alert);
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    fireEvent.mouseLeave(alert);
    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('pauses dismissal while focused and resumes after focus leaves', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="포커스 중인 알림" onDismiss={onDismiss} />);
    const alert = screen.getByRole('alert');
    const dismissButton = screen.getByRole('button', { name: '알림 닫기' });

    fireEvent.focus(dismissButton);
    act(() => {
      vi.advanceTimersByTime(6000);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    fireEvent.blur(dismissButton);
    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(alert).toBeInTheDocument();
  });

  it('does not render an empty message or schedule a dismissal', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="" onDismiss={onDismiss} />);

    act(() => {
      vi.advanceTimersByTime(6000);
    });

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it('remains paused when hover ends but keyboard focus is still inside', () => {
    const onDismiss = vi.fn();
    render(<FloatingNotice message="마우스와 키보드 사용 중" onDismiss={onDismiss} />);
    const alert = screen.getByRole('alert');
    const button = screen.getByRole('button', { name: '알림 닫기' });
    fireEvent.mouseEnter(alert);
    fireEvent.focus(button);
    fireEvent.mouseLeave(alert);
    act(() => { vi.advanceTimersByTime(10000); });
    expect(onDismiss).not.toHaveBeenCalled();
    fireEvent.blur(button);
    act(() => { vi.advanceTimersByTime(6000); });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
