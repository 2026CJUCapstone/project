import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, X } from 'lucide-react';
import './floating-notice.css';

interface FloatingNoticeProps {
  message: string;
  onDismiss: () => void;
  /** Zero keeps an unresolved load error visible until dismissed or resolved. */
  duration?: number;
}

export function FloatingNotice({ message, onDismiss, duration = 6000 }: FloatingNoticeProps) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const paused = hovered || focused;
  useEffect(() => {
    if (!message || duration <= 0 || paused) return;
    const timer = window.setTimeout(onDismiss, duration);
    return () => window.clearTimeout(timer);
  }, [message, onDismiss, duration, paused]);

  if (!message || typeof document === 'undefined') return null;
  return createPortal(
    <div className="floating-notice-layer" data-testid="floating-notice-layer">
      <div
        className="floating-notice"
        role="alert"
        aria-atomic="true"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocusCapture={() => setFocused(true)}
        onBlurCapture={event => {
          if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
            setFocused(false);
          }
        }}
      >
        <AlertCircle className="floating-notice-icon" size={19} aria-hidden="true" />
        <p className="floating-notice-message">{message}</p>
        <button type="button" className="floating-notice-dismiss" onClick={onDismiss} aria-label="알림 닫기">
          <X size={17} aria-hidden="true" />
        </button>
      </div>
    </div>,
    document.body,
  );
}
